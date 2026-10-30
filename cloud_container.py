""" ATM AWS container migration blueprint. Dependencies: pip install Flask boto3 paramiko The worker host also needs Docker CLI + a running Docker daemon. Set: ATM_SOURCE_RESOLVER=your_module:get_saved_source_connection ATM_CLOUD_MIGRATION_DB=/var/lib/atm/cloud_migration.sqlite3 (optional) Source resolver contract: get_saved_source_connection(source_connection_id) -> { "host": "...", "port": 22, "username": "...", "password": "...", "private_key": "...", "passphrase": "...", "runtime": "docker" or "podman", "known_hosts": "/path/to/known_hosts" # optional; recommended } The resolver MUST enforce that the authenticated user owns the connection. Register this blueprint behind the application's existing authentication/authorization. """

import base64
import importlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import boto3
import paramiko
from botocore.exceptions import ClientError, BotoCoreError
from flask import Blueprint, jsonify, request

bp = Blueprint("cloud_container_migration", __name__, url_prefix="/api/cloud-container-migration")

DB_PATH = os.environ.get("ATM_CLOUD_MIGRATION_DB", "/tmp/atm_cloud_container_migration.sqlite3")
MAX_WORKERS = int(os.environ.get("ATM_CLOUD_MIGRATION_MAX_WORKERS", "2"))
_WORKER_SEMAPHORE = threading.BoundedSemaphore(MAX_WORKERS)
_CANCEL = set()
_CANCEL_LOCK = threading.Lock()
_ALLOWED_REGIONS = None  # Set to a list of approved regions in your deployment if required.

# ---------------------------------------------------------------------------
# General helpers / persistent job records
# ---------------------------------------------------------------------------

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _db_connect():
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _db():
    conn = _db_connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db():
    with _db() as conn:
        conn.execute(""" CREATE TABLE IF NOT EXISTS cloud_migration_jobs ( job_id TEXT PRIMARY KEY, status TEXT NOT NULL, phase TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, source_connection_id TEXT NOT NULL, source_container_id TEXT NOT NULL, region TEXT NOT NULL, config_json TEXT NOT NULL, result_json TEXT, error_json TEXT ) """)


_init_db()


def _json_error(message, status=400, code="INVALID_REQUEST", details=None):
    return jsonify({"ok": False, "error": {
        "code": code, "message": message, "details": details or []
    }}), status


def _client_error(exc, operation=None):
    """Convert AWS errors into a UI-safe, actionable diagnostic."""
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        meta = exc.response.get("ResponseMetadata", {})
        code = err.get("Code", "AWS_CLIENT_ERROR")
        message = err.get("Message", str(exc))
        request_id = meta.get("RequestId")
        status = meta.get("HTTPStatusCode")
        if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation",
                    "AuthFailure", "Client.UnauthorizedOperation"):
            action = f"Grant the IAM principal permission for {operation or 'the attempted AWS action'}."
            if "explicit deny" in message.lower():
                action = "An explicit deny may be present in an SCP, permissions boundary, session policy, or IAM policy. Ask the AWS administrator to inspect the applicable policies."
            return {
                "code": code, "message": message, "operation": operation,
                "http_status": status, "request_id": request_id,
                "remediation": action
            }
        if "LimitExceeded" in code or "Quota" in code:
            remediation = "Check the account/region service quota and request an increase if appropriate."
        elif "InvalidParameter" in code or "Validation" in code:
            remediation = "Check the resource settings and region-specific constraints."
        elif "DependencyViolation" in code:
            remediation = "A dependent resource is still in use. Inspect the resource dependencies before retrying."
        elif "Throttl" in code or "RequestLimitExceeded" in code:
            remediation = "Retry with backoff; check service quotas if throttling continues."
        elif "NotFound" in code or "ResourceNotFound" in code:
            remediation = "The referenced resource does not exist in this region/account, or its identifier is incorrect."
        else:
            remediation = "Review the AWS error message and CloudTrail event for the attempted operation."
        return {
            "code": code, "message": message, "operation": operation,
            "http_status": status, "request_id": request_id, "remediation": remediation
        }
    if isinstance(exc, BotoCoreError):
        return {
            "code": type(exc).__name__, "message": str(exc),
            "operation": operation,
            "remediation": "Check AWS credentials, region, DNS/network connectivity, and system clock."
        }
    return {
        "code": type(exc).__name__, "message": str(exc), "operation": operation,
        "remediation": "Check backend logs for the traceback and verify the configuration."
    }


def _aws(region):
    if not region or not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise ValueError("A valid AWS region is required.")
    if _ALLOWED_REGIONS and region not in _ALLOWED_REGIONS:
        raise ValueError(f"Region {region} is not allowed by this deployment.")
    session = boto3.Session(region_name=region)
    # Explicitly call STS to validate the default credential chain.
    identity = session.client("sts").get_caller_identity()
    return session, identity


def _require_json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _source_resolver():
    spec = os.environ.get("ATM_SOURCE_RESOLVER", "")
    if ":" not in spec:
        raise RuntimeError("ATM_SOURCE_RESOLVER must be configured as module:function.")
    module_name, function_name = spec.split(":", 1)
    function = getattr(importlib.import_module(module_name), function_name)
    return function


def _source_connection(connection_id):
    if not connection_id:
        raise ValueError("sourceConnectionId is required.")
    data = _source_resolver()(connection_id)
    if not isinstance(data, dict) or not data.get("host") or not data.get("username"):
        raise RuntimeError("The ATM source adapter did not return host and username.")
    if not data.get("password") and not data.get("private_key"):
        raise RuntimeError("The source connection must contain a password or private_key.")
    return data


def _ssh_connect(source):
    client = paramiko.SSHClient()
    known_hosts = source.get("known_hosts") or os.environ.get("ATM_SSH_KNOWN_HOSTS")
    if known_hosts and os.path.isfile(known_hosts):
        client.load_host_keys(known_hosts)
    else:
        # Do not silently trust unknown host keys. Configure known_hosts for production.
        client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    kwargs = {
        "hostname": source["host"],
        "port": int(source.get("port") or 22),
        "username": source["username"],
        "timeout": 20,
        "banner_timeout": 20,
        "auth_timeout": 20,
        "look_for_keys": False,
        "allow_agent": False,
    }
    if source.get("private_key"):
        key_text = source["private_key"]
        key_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
        try:
            key_file.write(key_text)
            key_file.close()
            pkey = None
            for key_type in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
                try:
                    pkey = key_type.from_private_key_file(key_file.name, password=source.get("passphrase"))
                    break
                except Exception:
                    continue
            if pkey is None:
                raise ValueError("Unable to parse the SSH private key.")
            kwargs["pkey"] = pkey
        finally:
            try:
                os.unlink(key_file.name)
            except OSError:
                pass
    else:
        kwargs["password"] = source["password"]
    client.connect(**kwargs)
    return client


def _ssh_exec(client, command, timeout=300):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"Remote command failed (exit {code}): {command}\n{err[-4000:] or out[-4000:]}")
    return out


def _run_local(command, input_text=None, timeout=1800, env=None):
    completed = subprocess.run(
        command, input=input_text, text=True, capture_output=True,
        timeout=timeout, env=env, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Local command failed (exit {completed.returncode}): {shlex.join(command)}\n"
            f"{(completed.stderr or completed.stdout)[-5000:]}"
        )
    return completed.stdout


def _set_job(job_id, status=None, phase=None, progress=None, message=None, result=None, error=None):
    with _db() as conn:
        row = conn.execute("SELECT * FROM cloud_migration_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return
        values = {
            "status": status if status is not None else row["status"],
            "phase": phase if phase is not None else row["phase"],
            "progress": progress if progress is not None else row["progress"],
            "message": message if message is not None else row["message"],
            "updated_at": utc_now(),
            "result_json": json.dumps(result) if result is not None else row["result_json"],
            "error_json": json.dumps(error) if error is not None else row["error_json"],
        }
        conn.execute(""" UPDATE cloud_migration_jobs SET status=?, phase=?, progress=?, message=?, updated_at=?, result_json=?, error_json=? WHERE job_id=? """, (values["status"], values["phase"], values["progress"], values["message"],
              values["updated_at"], values["result_json"], values["error_json"], job_id))


def _get_job(job_id):
    with _db() as conn:
        row = conn.execute("SELECT * FROM cloud_migration_jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["config"] = json.loads(item.pop("config_json"))
    item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
    item["error"] = json.loads(item.pop("error_json")) if item.get("error_json") else None
    return item


def _cancelled(job_id):
    with _CANCEL_LOCK:
        return job_id in _CANCEL


def _check_cancel(job_id):
    if _cancelled(job_id):
        raise RuntimeError("Migration cancelled by user at a safe checkpoint.")


# ---------------------------------------------------------------------------
# AWS infrastructure discovery and provisioning
# ---------------------------------------------------------------------------

def _describe_vpcs(ec2):
    result = []
    for page in ec2.get_paginator("describe_vpcs").paginate():
        result.extend(page.get("Vpcs", []))
    return result


def _network_inventory(session):
    ec2 = session.client("ec2")
    vpcs = _describe_vpcs(ec2)
    subnets = []
    for page in ec2.get_paginator("describe_subnets").paginate():
        subnets.extend(page.get("Subnets", []))
    igws = []
    for page in ec2.get_paginator("describe_internet_gateways").paginate():
        igws.extend(page.get("InternetGateways", []))
    routes = []
    for page in ec2.get_paginator("describe_route_tables").paginate():
        routes.extend(page.get("RouteTables", []))
    return ec2, vpcs, subnets, igws, routes


def _tag_value(resource, key):
    return next((t.get("Value") for t in resource.get("Tags", []) if t.get("Key") == key), None)


def _public_subnet_ids(vpc_id, subnets, route_tables):
    associations = {}
    for rt in route_tables:
        is_public = any(
            r.get("DestinationCidrBlock") == "0.0.0.0/0" and r.get("GatewayId", "").startswith("igw-")
            for r in rt.get("Routes", [])
        )
        if not is_public:
            continue
        for assoc in rt.get("Associations", []):
            if assoc.get("SubnetId"):
                associations[assoc["SubnetId"]] = True
            elif assoc.get("Main"):
                associations[f"main:{rt.get('VpcId')}"] = True
    ids = []
    main_public = associations.get(f"main:{vpc_id}", False)
    for subnet in subnets:
        if subnet.get("VpcId") != vpc_id:
            continue
        if associations.get(subnet["SubnetId"]) or main_public:
            ids.append(subnet["SubnetId"])
    return ids


def _find_compatible_network(vpcs, subnets, route_tables):
    # Prefer a default VPC, then a VPC with at least two subnets in different AZs,
    # then any VPC with at least one subnet.
    candidates = []
    for vpc in vpcs:
        if vpc.get("State") != "available":
            continue
        own = [s for s in subnets if s.get("VpcId") == vpc["VpcId"] and s.get("State") == "available"]
        if not own:
            continue
        public = _public_subnet_ids(vpc["VpcId"], own, route_tables)
        azs = {s.get("AvailabilityZone") for s in own}
        score = (100 if vpc.get("IsDefault") else 0) + (30 if len(azs) >= 2 else 0) + (20 if len(public) >= 2 else 0) + len(own)
        candidates.append((score, vpc, own, public))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, vpc, own, public = candidates[0]
    # ECS service creation needs two subnets in distinct AZs for broad compatibility.
    preferred = public if len(public) >= 2 else [s["SubnetId"] for s in own]
    chosen = []
    used_az = set()
    for sid in preferred:
        subnet = next((s for s in own if s["SubnetId"] == sid), None)
        if subnet and subnet.get("AvailabilityZone") not in used_az:
            chosen.append(sid)
            used_az.add(subnet.get("AvailabilityZone"))
        if len(chosen) >= 4:
            break
    return {"vpc": vpc, "subnets": own, "public_subnet_ids": public, "recommended_subnet_ids": chosen}


def _diagnostic_for_call(operation, fn):
    try:
        return {"ok": True, "value": fn()}
    except Exception as exc:
        return {"ok": False, "diagnostic": _client_error(exc, operation)}


def _inspect_infrastructure(session, identity):
    report = {
        "identity": {"account": identity.get("Account"), "arn": identity.get("Arn"), "userId": identity.get("UserId")},
        "checks": [], "resources": {}, "canProvision": True, "networking": {}
    }
    region = session.region_name
    report["region"] = region
    # ECR access / repositories
    ecr = session.client("ecr")
    report["checks"].append(_diagnostic_for_call("ecr:DescribeRepositories", lambda: ecr.describe_repositories(maxResults=1)))
    ecs = session.client("ecs")
    report["checks"].append(_diagnostic_for_call("ecs:ListClusters", lambda: ecs.list_clusters(maxResults=1)))
    logs = session.client("logs")
    report["checks"].append(_diagnostic_for_call("logs:DescribeLogGroups", lambda: logs.describe_log_groups(limit=1)))
    iam = session.client("iam")
    report["checks"].append(_diagnostic_for_call("iam:GetRole", lambda: iam.get_role(RoleName="ecsTaskExecutionRole")))
    try:
        ec2, vpcs, subnets, igws, route_tables = _network_inventory(session)
        selected = _find_compatible_network(vpcs, subnets, route_tables)
        report["networking"] = {
            "vpcs": [{"id": v["VpcId"], "cidr": v.get("CidrBlock"), "default": v.get("IsDefault"), "state": v.get("State")} for v in vpcs],
            "subnets": [{"id": s["SubnetId"], "vpcId": s.get("VpcId"), "az": s.get("AvailabilityZone"),
                         "cidr": s.get("CidrBlock"), "publicIpOnLaunch": s.get("MapPublicIpOnLaunch")} for s in subnets],
            "internetGateways": [{"id": g["InternetGatewayId"], "vpcIds": [a.get("VpcId") for a in g.get("Attachments", [])]} for g in igws],
            "selected": None if not selected else {
                "vpcId": selected["vpc"]["VpcId"],
                "subnetIds": selected["recommended_subnet_ids"],
                "publicSubnetIds": selected["public_subnet_ids"],
                "defaultVpc": selected["vpc"].get("IsDefault")
            }
        }
        report["resources"]["network"] = {
            "status": "ready" if selected and len(selected["recommended_subnet_ids"]) >= 2 else
                      "partial" if selected else "missing",
            "message": "Compatible existing VPC/subnets found." if selected else
                       "No existing VPC with available subnets was found."
        }
    except Exception as exc:
        report["networking"] = {}
        report["resources"]["network"] = {"status": "unknown", "diagnostic": _client_error(exc, "ec2:DescribeVpcs/DescribeSubnets")}
    try:
        clusters = ecs.list_clusters().get("clusterArns", [])
        described = ecs.describe_clusters(clusters=clusters, include=["ATTACHMENTS", "CONFIGURATIONS"]) if clusters else {"clusters": []}
        report["resources"]["ecsClusters"] = [
            {"arn": c.get("clusterArn"), "name": c.get("clusterName"), "status": c.get("status")}
            for c in described.get("clusters", []) if c.get("status") == "ACTIVE"
        ]
        report["resources"]["ecsClusterStatus"] = "ready" if report["resources"]["ecsClusters"] else "missing"
    except Exception as exc:
        report["resources"]["ecsClusters"] = []
        report["resources"]["ecsClusterStatus"] = "unknown"
        report["checks"].append({"ok": False, "diagnostic": _client_error(exc, "ecs:ListClusters/DescribeClusters")})
    try:
        roles = iam.list_roles(PathPrefix="/").get("Roles", [])
        execution = next((r for r in roles if r.get("RoleName") == "ecsTaskExecutionRole"), None)
        report["resources"]["executionRole"] = {
            "status": "ready" if execution else "missing",
            "arn": execution.get("Arn") if execution else None,
            "name": execution.get("RoleName") if execution else "ecsTaskExecutionRole"
        }
    except Exception as exc:
        report["resources"]["executionRole"] = {"status": "unknown", "diagnostic": _client_error(exc, "iam:ListRoles")}
    return report


def _ensure_execution_role(session, role_name="ecsTaskExecutionRole"):
    iam = session.client("iam")
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                       "Action": "sts:AssumeRole"}]
    }
    try:
        role = iam.get_role(RoleName=role_name)["Role"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("NoSuchEntity", "NoSuchEntityException"):
            raise
        role = iam.create_role(
            RoleName=role_name, AssumeRolePolicyDocument=json.dumps(trust),
            Description="ECS task execution role managed by ATM container migration",
            Tags=[{"Key": "ManagedBy", "Value": "ATM"}]
        )["Role"]
    iam.update_assume_role_policy(RoleName=role_name, 