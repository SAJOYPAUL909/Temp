"""
ATM AWS container migration blueprint.

Dependencies:
    pip install Flask boto3 paramiko

The worker host also needs Docker CLI + a running Docker daemon.
Set:
    ATM_SOURCE_RESOLVER=your_module:get_saved_source_connection
    ATM_CLOUD_MIGRATION_DB=/var/lib/atm/cloud_migration.sqlite3  (optional)

Source resolver contract:
    get_saved_source_connection(source_connection_id) -> {
        "host": "...", "port": 22, "username": "...",
        "password": "...", "private_key": "...", "passphrase": "...",
        "runtime": "docker" or "podman",
        "known_hosts": "/path/to/known_hosts"  # optional; recommended
    }
The resolver MUST enforce that the authenticated user owns the connection.
Register this blueprint behind the application's existing authentication/authorization.
"""

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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS cloud_migration_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_container_id TEXT NOT NULL,
            region TEXT NOT NULL,
            config_json TEXT NOT NULL,
            result_json TEXT,
            error_json TEXT
        )
        """)


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


def _set_job(job_id, status=None, phase=None, progress=None, message=None,
             result=None, error=None):
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
        conn.execute("""
            UPDATE cloud_migration_jobs SET status=?, phase=?, progress=?, message=?,
            updated_at=?, result_json=?, error_json=? WHERE job_id=?
        """, (values["status"], values["phase"], values["progress"], values["message"],
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
    iam.update_assume_role_policy(RoleName=role_name, PolicyDocument=json.dumps(trust))
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    )
    return role["Arn"]


def _ensure_network(session, allow_create=True):
    """Reuse an existing VPC only when it has two public subnets in distinct AZs.

    If no compatible network exists, create a dedicated public VPC with two public
    subnets and an Internet Gateway. Never create a NAT gateway automatically.
    Existing private subnets are not silently converted to public subnets.
    """
    ec2, vpcs, subnets, igws, route_tables = _network_inventory(session)
    selected = _find_compatible_network(vpcs, subnets, route_tables)
    if selected and len(selected["public_subnet_ids"]) >= 2:
        public = selected["public_subnet_ids"]
        chosen = []
        used_az = set()
        for subnet in selected["subnets"]:
            if subnet["SubnetId"] in public and subnet.get("AvailabilityZone") not in used_az:
                chosen.append(subnet["SubnetId"])
                used_az.add(subnet.get("AvailabilityZone"))
            if len(chosen) >= 4:
                break
        if len(chosen) >= 2:
            return {"vpc_id": selected["vpc"]["VpcId"], "subnet_ids": chosen,
                    "public_subnet_ids": chosen, "created": False, "public_ip_default": True}
    if not allow_create:
        raise RuntimeError("No compatible VPC with two public subnets in separate Availability Zones was found.")

    # Create a separate VPC only because no suitable existing public network was found.
    # Select a /16 that does not overlap the IPv4 CIDRs currently assigned to VPCs.
    existing_networks = []
    for vpc in vpcs:
        for assoc in vpc.get("CidrBlockAssociationSet", []):
            cidr = assoc.get("CidrBlock")
            if cidr and assoc.get("CidrBlockState", {}).get("State") == "associated":
                try:
                    existing_networks.append(ipaddress.ip_network(cidr))
                except ValueError:
                    pass
    candidate = None
    for third_octet in range(240, 256):
        net = ipaddress.ip_network(f"10.{third_octet}.0.0/16")
        if not any(net.overlaps(old) for old in existing_networks):
            candidate = str(net)
            break
    if not candidate:
        raise RuntimeError("Could not find a non-overlapping 10.x.0.0/16 CIDR for the new VPC. Configure a suitable VPC CIDR manually.")

    azs = ec2.describe_availability_zones(
        Filters=[{"Name": "state", "Values": ["available"]}]
    )["AvailabilityZones"]
    if len(azs) < 2:
        raise RuntimeError("At least two available Availability Zones are required to create a Fargate network.")
    azs = azs[:2]
    vpc = ec2.create_vpc(
        CidrBlock=candidate,
        TagSpecifications=[{"ResourceType": "vpc", "Tags": [
            {"Key": "Name", "Value": "atm-migration-vpc"}, {"Key": "ManagedBy", "Value": "ATM"}
        ]}]
    )["Vpc"]
    vpc_id = vpc["VpcId"]
    ec2.get_waiter("vpc_available").wait(VpcIds=[vpc_id])
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})

    igw = ec2.create_internet_gateway(
        TagSpecifications=[{"ResourceType": "internet-gateway", "Tags": [{"Key": "ManagedBy", "Value": "ATM"}]}]
    )["InternetGateway"]
    igw_id = igw["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
    route_table = ec2.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[{"ResourceType": "route-table", "Tags": [{"Key": "ManagedBy", "Value": "ATM"}]}]
    )["RouteTable"]
    ec2.create_route(RouteTableId=route_table["RouteTableId"], DestinationCidrBlock="0.0.0.0/0", GatewayId=igw_id)
    subnet_ids = []
    for idx, az in enumerate(azs):
        subnet = ec2.create_subnet(
            VpcId=vpc_id, CidrBlock=f"10.{int(candidate.split('.')[1])}.{idx + 1}.0/24", AvailabilityZone=az["ZoneName"],
            TagSpecifications=[{"ResourceType": "subnet", "Tags": [
                {"Key": "Name", "Value": f"atm-public-{az['ZoneName']}"}, {"Key": "ManagedBy", "Value": "ATM"}
            ]}]
        )["Subnet"]
        sid = subnet["SubnetId"]
        ec2.modify_subnet_attribute(SubnetId=sid, MapPublicIpOnLaunch={"Value": True})
        ec2.associate_route_table(RouteTableId=route_table["RouteTableId"], SubnetId=sid)
        subnet_ids.append(sid)
    return {"vpc_id": vpc_id, "subnet_ids": subnet_ids, "public_subnet_ids": subnet_ids,
            "created": True, "public_ip_default": True,
            "notice": "Created a dedicated public VPC because no compatible existing public subnets were found. No NAT gateway was created; NAT gateway creation remains an explicit, separately approved operation."}


def _ensure_security_group(session, vpc_id, port=None):
    ec2 = session.client("ec2")
    name = "atm-ecs-task-sg"
    groups = ec2.describe_security_groups(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}, {"Name": "group-name", "Values": [name]}]
    ).get("SecurityGroups", [])
    if groups:
        sg_id = groups[0]["GroupId"]
    else:
        sg_id = ec2.create_security_group(
            GroupName=name, Description="ATM ECS task security group; inbound rules are explicitly configured",
            VpcId=vpc_id, TagSpecifications=[{"ResourceType": "security-group", "Tags": [{"Key": "ManagedBy", "Value": "ATM"}]}]
        )["GroupId"]
    # Never open inbound ports to 0.0.0.0/0 automatically. Users can add an approved CIDR separately.
    if port:
        existing = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0].get("IpPermissions", [])
        already = any(p.get("IpProtocol") == "tcp" and p.get("FromPort") == int(port) and p.get("ToPort") == int(port) for p in existing)
        if not already:
            # No public CIDR is added; this only creates a self-referencing rule for tasks in this SG.
            ec2.authorize_security_group_ingress(
                GroupId=sg_id, IpPermissions=[{"IpProtocol": "tcp", "FromPort": int(port), "ToPort": int(port),
                    "UserIdGroupPairs": [{"GroupId": sg_id, "Description": "Allow task-to-task traffic on application port"}]}]
            )
    return sg_id


def _ensure_log_group(session, log_group, retention_days=30):
    logs = session.client("logs")
    try:
        logs.create_log_group(logGroupName=log_group, tags={"ManagedBy": "ATM"})
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("ResourceAlreadyExistsException",):
            raise
    logs.put_retention_policy(logGroupName=log_group, retentionInDays=int(retention_days))
    return log_group


def _ensure_cluster(session, cluster_name):
    ecs = session.client("ecs")
    data = ecs.describe_clusters(clusters=[cluster_name])
    clusters = data.get("clusters", [])
    failures = data.get("failures", [])
    if clusters and clusters[0].get("status") == "ACTIVE":
        return clusters[0]["clusterArn"], False
    # Do not turn AccessDenied or other AWS failures into an attempted create.
    missing = not clusters or any(f.get("reason") == "MISSING" for f in failures)
    if not missing:
        raise RuntimeError("ECS cluster is not active and AWS did not report it as missing: " + json.dumps(failures))
    created = ecs.create_cluster(clusterName=cluster_name, tags=[{"key": "ManagedBy", "value": "ATM"}])
    return created["cluster"]["clusterArn"], True


def _ensure_ecr(session, repository_name):
    ecr = session.client("ecr")
    try:
        repo = ecr.describe_repositories(repositoryNames=[repository_name])["repositories"][0]
        return repo, False
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "RepositoryNotFoundException":
            raise
    repo = ecr.create_repository(
        repositoryName=repository_name,
        imageTagMutability="IMMUTABLE",
        imageScanningConfiguration={"scanOnPush": True},
        encryptionConfiguration={"encryptionType": "AES256"},
        tags=[{"Key": "ManagedBy", "Value": "ATM"}]
    )["repository"]
    return repo, True


@bp.post("/inspect")
def inspect_aws():
    body = _require_json()
    region = body.get("region")
    if not region:
        return _json_error("region is required.", 400)
    try:
        session, identity = _aws(region)
        report = _inspect_infrastructure(session, identity)
        return jsonify({"ok": True, "report": report})
    except Exception as exc:
        return jsonify({"ok": False, "error": _client_error(exc, "sts:GetCallerIdentity")}), 400


@bp.post("/prepare")
def prepare_infrastructure():
    """
    Creates/reuses only the baseline resources required by this workflow.
    Does NOT create a NAT gateway and does NOT open inbound access to the internet.
    A production app should enforce authorization and optionally require an admin approval
    token for infrastructure creation.
    """
    body = _require_json()
    region = body.get("region")
    if not region:
        return _json_error("region is required.", 400)
    try:
        session, identity = _aws(region)
        created = []
        warnings = []
        diagnostics = []
        repository_name = body.get("repositoryName") or "atm-migrated-apps"
        cluster_name = body.get("clusterName") or "atm-migration-cluster"
        log_group = body.get("logGroup") or "/ecs/atm-migration"
        role_name = body.get("executionRoleName") or "ecsTaskExecutionRole"
        port = body.get("containerPort")
        if port is not None and (not isinstance(port, int) or port < 1 or port > 65535):
            return _json_error("containerPort must be an integer between 1 and 65535.")
        # Existing infrastructure first; provision only when a resource is absent.
        repo, repo_created = _ensure_ecr(session, repository_name)
        created.append({"type": "ECR repository", "created": repo_created, "name": repo["repositoryName"], "uri": repo["repositoryUri"]})
        cluster_arn, cluster_created = _ensure_cluster(session, cluster_name)
        created.append({"type": "ECS cluster", "created": cluster_created, "name": cluster_name, "arn": cluster_arn})
        iam = session.client("iam")
        try:
            iam.get_role(RoleName=role_name)
            role_existed = True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("NoSuchEntity", "NoSuchEntityException"):
                raise
            role_existed = False
        execution_role_arn = _ensure_execution_role(session, role_name)
        created.append({"type": "ECS execution role", "created": not role_existed, "name": role_name, "arn": execution_role_arn})
        logs = session.client("logs")
        try:
            log_existed = any(x.get("logGroupName") == log_group for x in logs.describe_log_groups(logGroupNamePrefix=log_group, limit=50).get("logGroups", []))
        except ClientError:
            log_existed = False
        log_name = _ensure_log_group(session, log_group, int(body.get("logRetentionDays") or 30))
        created.append({"type": "CloudWatch log group", "created": not log_existed, "name": log_name})
        network = _ensure_network(session, allow_create=True)
        created.append({"type": "VPC/subnets/routes", "created": network.get("created", False),
                        "vpcId": network["vpc_id"], "subnetIds": network["subnet_ids"]})
        if network.get("notice"):
            warnings.append(network["notice"])
        sg_id = _ensure_security_group(session, network["vpc_id"], port)
        created.append({"type": "Security group", "created": True, "id": sg_id})
        return jsonify({"ok": True, "region": region, "account": identity.get("Account"),
            "resources": {"repository": repo, "clusterArn": cluster_arn, "clusterName": cluster_name,
                "executionRoleArn": execution_role_arn, "logGroup": log_name,
                "vpcId": network["vpc_id"], "subnetIds": network["subnet_ids"],
                "securityGroupIds": [sg_id], "assignPublicIp": network.get("public_ip_default", True)},
            "actions": created, "warnings": warnings, "diagnostics": diagnostics})
    except Exception as exc:
        diagnostic = _client_error(exc, "AWS infrastructure provisioning")
        return jsonify({"ok": False, "error": diagnostic,
            "message": "Infrastructure preparation stopped at the first required operation that failed. Earlier successful resources may remain; inspect AWS and rerun safely."}), 400


@bp.post("/containers")
def list_source_containers():
    body = _require_json()
    try:
        source = _source_connection(body.get("sourceConnectionId"))
        client = _ssh_connect(source)
        try:
            runtime = source.get("runtime") or body.get("runtime") or "auto"
            runtimes = [runtime] if runtime in ("docker", "podman") else ["podman", "docker"]
            errors = []
            for candidate in runtimes:
                probe = client.exec_command(f"command -v {candidate} >/dev/null 2>&1")[1]
                if probe.channel.recv_exit_status() != 0:
                    errors.append(f"{candidate} is not installed or not available to this SSH user.")
                    continue
                check = _ssh_exec(client, f"{candidate} ps -a --no-trunc --format '{{{{json .}}}}'", timeout=60)
                containers = []
                for line in check.splitlines():
                    try:
                        row = json.loads(line)
                        containers.append({
                            "id": row.get("ID"), "name": row.get("Names"),
                            "image": row.get("Image"), "status": row.get("Status"),
                            "ports": row.get("Ports", ""), "runtime": candidate
                        })
                    except json.JSONDecodeError:
                        continue
                return jsonify({"ok": True, "runtime": candidate, "containers": containers})
            return _json_error("Neither Docker nor Podman returned a container list.", 400, "CONTAINER_RUNTIME_NOT_FOUND", errors)
        finally:
            client.close()
    except Exception as exc:
        return jsonify({"ok": False, "error": _client_error(exc, "SSH/source container discovery")}), 400


def _job_public(job):
    return {
        "jobId": job["job_id"], "status": job["status"], "phase": job["phase"],
        "progress": job["progress"], "message": job["message"],
        "createdAt": job["created_at"], "updatedAt": job["updated_at"],
        "result": job["result"], "error": job["error"]
    }


def _migration_worker(job_id):
    if not _WORKER_SEMAPHORE.acquire(blocking=False):
        _set_job(job_id, status="failed", phase="queue", message="Worker capacity is full.",
                 error={"code": "WORKER_CAPACITY", "message": "Worker capacity is full.",
                        "remediation": "Retry later or configure a durable job queue."})
        return
    tempdir = None
    client = None
    docker_config_dir = None
    try:
        job = _get_job(job_id)
        if not job:
            return
        cfg = job["config"]
        region = job["region"]
        session, identity = _aws(region)
        source = _source_connection(job["source_connection_id"])
        _check_cancel(job_id)
        _set_job(job_id, status="running", phase="source-export", progress=5, message="Connecting to source VM.")
        client = _ssh_connect(source)
        runtime = source.get("runtime") or "auto"
        if runtime not in ("docker", "podman"):
            for candidate in ("podman", "docker"):
                probe = client.exec_command(f"command -v {candidate} >/dev/null 2>&1")[1]
                if probe.channel.recv_exit_status() == 0:
                    runtime = candidate
                    break
        if runtime not in ("docker", "podman"):
            raise RuntimeError("Neither Docker nor Podman is available to the source SSH user.")
        container_id = job["source_container_id"]
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", container_id)
        if not safe_id:
            raise ValueError("Invalid container ID.")
        image_ref = _ssh_exec(client, f"{runtime} inspect --format '{{{{.Config.Image}}}}' {shlex.quote(safe_id)}", timeout=60).strip()
        if not image_ref:
            raise RuntimeError("Unable to identify the source container image.")
        image_id = _ssh_exec(client, f"{runtime} inspect --format '{{{{.Image}}}}' {shlex.quote(safe_id)}", timeout=60).strip()
        _ssh_exec(client, f"{runtime} image save -o /tmp/atm-migrate-{job_id}.tar {shlex.quote(image_ref)}", timeout=1800)
        _check_cancel(job_id)
        _set_job(job_id, phase="download-image", progress=20, message="Downloading exported image from source VM.")
        tempdir = tempfile.mkdtemp(prefix="atm-cloud-migrate-")
        tar_path = os.path.join(tempdir, "image.tar")
        sftp = client.open_sftp()
        try:
            sftp.get(f"/tmp/atm-migrate-{job_id}.tar", tar_path)
            sftp.remove(f"/tmp/atm-migrate-{job_id}.tar")
        finally:
            sftp.close()
        _check_cancel(job_id)
        _set_job(job_id, phase="prepare-aws", progress=30, message="Validating AWS resources.")
        repo, _ = _ensure_ecr(session, cfg["repositoryName"])
        account_id = identity["Account"]
        ecr = session.client("ecr")
        auth = ecr.get_authorization_token()["authorizationData"][0]
        user_pass = base64.b64decode(auth["authorizationToken"]).decode("utf-8")
        username, password = user_pass.split(":", 1)
        registry = auth["proxyEndpoint"].replace("https://", "")
        docker_config_dir = tempfile.mkdtemp(prefix="atm-docker-config-")
        env = os.environ.copy()
        env["DOCKER_CONFIG"] = docker_config_dir
        _run_local(["docker", "login", "--username", username, "--password-stdin", registry],
                   input_text=password, timeout=60, env=env)
        _check_cancel(job_id)
        _set_job(job_id, phase="load-and-push", progress=45, message="Loading image and pushing it to ECR.")
        _run_local(["docker", "load", "--input", tar_path], timeout=1800, env=env)
        tag = f"atm-{job_id[:8]}-{int(time.time())}"
        target_uri = f"{repo['repositoryUri']}:{tag}"
        # Docker load may assign a tag different from inspect's .Config.Image; image ID is stable.
        _run_local(["docker", "tag", image_id, target_uri], timeout=120, env=env)
        _run_local(["docker", "push", target_uri], timeout=1800, env=env)
        image_details = ecr.describe_images(repositoryName=cfg["repositoryName"], imageIds=[{"imageTag": tag}])
        digest = image_details["imageDetails"][0].get("imageDigest")
        _check_cancel(job_id)
        _set_job(job_id, phase="deploy-ecs", progress=65, message="Preparing ECS task definition and service.")
        network = _ensure_network(session, allow_create=True)
        # Honor explicitly selected subnet/security-group IDs, but verify the subnets exist.
        requested_subnets = cfg.get("subnetIds") or []
        if requested_subnets:
            ec2 = session.client("ec2")
            found = ec2.describe_subnets(SubnetIds=requested_subnets).get("Subnets", [])
            if len(found) != len(set(requested_subnets)):
                raise RuntimeError("One or more configured subnetIds were not found or are duplicated.")
            vpc_ids = {x.get("VpcId") for x in found}
            if len(vpc_ids) != 1:
                raise RuntimeError("All selected subnets must belong to the same VPC.")
            network["vpc_id"] = next(iter(vpc_ids))
            network["subnet_ids"] = list(dict.fromkeys(requested_subnets))
            network["public_ip_default"] = all(bool(x.get("MapPublicIpOnLaunch")) for x in found)
        sg_ids = cfg.get("securityGroupIds") or []
        if sg_ids:
            groups = session.client("ec2").describe_security_groups(GroupIds=sg_ids).get("SecurityGroups", [])
            if len(groups) != len(set(sg_ids)) or any(g.get("VpcId") != network["vpc_id"] for g in groups):
                raise RuntimeError("All configured securityGroupIds must exist and belong to the selected subnet VPC.")
        else:
            sg_ids = [_ensure_security_group(session, network["vpc_id"], cfg.get("containerPort"))]
        role_arn = cfg.get("executionRoleArn") or _ensure_execution_role(session, cfg.get("executionRoleName") or "ecsTaskExecutionRole")
        cluster_arn, _ = _ensure_cluster(session, cfg.get("clusterName") or "atm-migration-cluster")
        log_group = cfg.get("logGroup") or "/ecs/atm-migration"
        _ensure_log_group(session, log_group, int(cfg.get("logRetentionDays") or 30))
        family = cfg.get("taskFamily") or re.sub(r"[^A-Za-z0-9_-]", "-", cfg.get("serviceName", "atm-app"))[:255]
        container_name = cfg.get("containerName") or "app"
        cpu = str(cfg.get("cpu") or "256")
        memory = str(cfg.get("memory") or "512")
        port = cfg.get("containerPort")
        container_def = {
            "name": container_name, "image": target_uri, "essential": True,
            "logConfiguration": {"logDriver": "awslogs", "options": {
                "awslogs-group": log_group, "awslogs-region": region, "awslogs-stream-prefix": "ecs"
            }}
        }
        if port:
            container_def["portMappings"] = [{"containerPort": int(port), "protocol": "tcp"}]
        if cfg.get("healthCheckCommand"):
            container_def["healthCheck"] = {
                "command": ["CMD-SHELL", cfg["healthCheckCommand"]],
                "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 60
            }
        task = session.client("ecs").register_task_definition(
            family=family, networkMode="awsvpc", requiresCompatibilities=["FARGATE"],
            cpu=cpu, memory=memory, executionRoleArn=role_arn,
            runtimePlatform={"operatingSystemFamily": "LINUX", "cpuArchitecture": cfg.get("architecture", "X86_64")},
            containerDefinitions=[container_def],
            tags=[{"key": "ManagedBy", "value": "ATM"}, {"key": "MigrationJobId", "value": job_id}],
            **({"taskRoleArn": cfg["taskRoleArn"]} if cfg.get("taskRoleArn") else {})
        )["taskDefinition"]
        ecs = session.client("ecs")
        service_name = cfg["serviceName"]
        service_desc = ecs.describe_services(cluster=cluster_arn, services=[service_name])
        active_services = [s for s in service_desc.get("services", []) if s.get("status") == "ACTIVE"]
        if active_services:
            ecs.update_service(cluster=cluster_arn, service=service_name,
                taskDefinition=task["taskDefinitionArn"], desiredCount=int(cfg.get("desiredCount") or 1),
                forceNewDeployment=True)
        else:
            ecs.create_service(
                cluster=cluster_arn, serviceName=service_name,
                taskDefinition=task["taskDefinitionArn"], desiredCount=int(cfg.get("desiredCount") or 1),
                launchType="FARGATE", platformVersion="LATEST",
                networkConfiguration={"awsvpcConfiguration": {
                    "subnets": network["subnet_ids"],
                    "securityGroups": sg_ids,
                    "assignPublicIp": "ENABLED" if cfg.get("assignPublicIp", network.get("public_ip_default", True)) else "DISABLED"
                }},
                deploymentConfiguration={"maximumPercent": 200, "minimumHealthyPercent": 50},
                enableECSManagedTags=True,
                tags=[{"key": "ManagedBy", "value": "ATM"}, {"key": "MigrationJobId", "value": job_id}]
            )
        _set_job(job_id, phase="wait-for-service", progress=80, message="Waiting for ECS service stability.")
        waiter = ecs.get_waiter("services_stable")
        waiter.wait(cluster=cluster_arn, services=[service_name], WaiterConfig={"Delay": 15, "MaxAttempts": 40})
        _check_cancel(job_id)
        service = ecs.describe_services(cluster=cluster_arn, services=[service_name])["services"][0]
        tasks = ecs.list_tasks(cluster=cluster_arn, serviceName=service_name, desiredStatus="RUNNING").get("taskArns", [])
        task_details = ecs.describe_tasks(cluster=cluster_arn, tasks=tasks)["tasks"] if tasks else []
        running = [t for t in task_details if t.get("lastStatus") == "RUNNING"]
        if int(cfg.get("desiredCount") or 1) > 0 and not running:
            failures = service.get("events", [])[:8]
            raise RuntimeError("ECS service stabilized without a running task. Recent ECS events: " + json.dumps(failures))
        result = {
            "account": account_id, "region": region, "sourceImage": image_ref, "sourceImageId": image_id,
            "ecrRepository": cfg["repositoryName"], "imageUri": target_uri, "imageDigest": digest,
            "clusterArn": cluster_arn, "serviceName": service_name,
            "taskDefinitionArn": task["taskDefinitionArn"],
            "runningTaskCount": len(running), "desiredCount": int(cfg.get("desiredCount") or 1),
            "network": {"vpcId": network["vpc_id"], "subnetIds": network["subnet_ids"], "securityGroupIds": sg_ids},
            "notes": [
                "This migrates the container image, not its runtime environment, secrets, bind mounts, named volumes, host networking, or external dependencies.",
                "ECS RUNNING status is not proof of application-level health; configure a container health check and/or an authenticated HTTP smoke test."
            ]
        }
        _set_job(job_id, status="succeeded", phase="completed", progress=100,
                 message="Image pushed to ECR and ECS service is running.", result=result)
    except Exception as exc:
        diag = _client_error(exc, "container migration / ECR / ECS")
        _set_job(job_id, status="cancelled" if _cancelled(job_id) else "failed",
                 phase="failed", message=diag.get("message", str(exc)), error=diag)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
        if docker_config_dir:
            shutil.rmtree(docker_config_dir, ignore_errors=True)
        _WORKER_SEMAPHORE.release()
        with _CANCEL_LOCK:
            _CANCEL.discard(job_id)


@bp.post("/jobs")
def create_migration_job():
    body = _require_json()
    required = ["sourceConnectionId", "containerId", "region", "repositoryName", "serviceName"]
    missing = [key for key in required if not body.get(key)]
    if missing:
        return _json_error("Missing required fields: " + ", ".join(missing))
    try:
        # Validate source connectivity and AWS identity before queueing the job.
        source = _source_connection(body["sourceConnectionId"])
        ssh = _ssh_connect(source)
        ssh.close()
        session, identity = _aws(body["region"])
        cpu = str(body.get("cpu") or "256")
        memory = str(body.get("memory") or "512")
        # Fargate supported CPU/memory pairs; AWS remains authoritative.
        allowed = {
            "256": {"512", "1024", "2048"},
            "512": {"1024", "2048", "3072", "4096"},
            "1024": {str(x) for x in range(2048, 8193, 1024)},
            "2048": {str(x) for x in range(4096, 16385, 1024)},
            "4096": {str(x) for x in range(8192, 30721, 1024)},
            "8192": {str(x) for x in range(16384, 61441, 4096)},
            "16384": {str(x) for x in range(32768, 122881, 8192)},
        }
        if cpu not in allowed or memory not in allowed[cpu]:
            return _json_error(f"Unsupported Fargate CPU/memory combination: {cpu}/{memory}.")
        port = body.get("containerPort")
        if port is not None and (not isinstance(port, int) or not 1 <= port <= 65535):
            return _json_error("containerPort must be an integer between 1 and 65535.")
        config = {
            "repositoryName": body["repositoryName"], "clusterName": body.get("clusterName") or "atm-migration-cluster",
            "serviceName": body["serviceName"], "taskFamily": body.get("taskFamily"),
            "containerName": body.get("containerName") or "app", "cpu": cpu, "memory": memory,
            "containerPort": port, "desiredCount": int(body.get("desiredCount") or 1),
            "assignPublicIp": bool(body.get("assignPublicIp", True)),
            "subnetIds": body.get("subnetIds") or [], "securityGroupIds": body.get("securityGroupIds") or [],
            "executionRoleArn": body.get("executionRoleArn"), "executionRoleName": body.get("executionRoleName") or "ecsTaskExecutionRole",
            "taskRoleArn": body.get("taskRoleArn"), "logGroup": body.get("logGroup") or "/ecs/atm-migration",
            "logRetentionDays": int(body.get("logRetentionDays") or 30),
            "architecture": body.get("architecture") or "X86_64",
            "healthCheckCommand": body.get("healthCheckCommand")
        }
        if config["desiredCount"] < 0 or config["desiredCount"] > 100:
            return _json_error("desiredCount must be between 0 and 100.")
        job_id = str(uuid.uuid4())
        with _db() as conn:
            conn.execute("""
            INSERT INTO cloud_migration_jobs
            (job_id,status,phase,progress,message,created_at,updated_at,source_connection_id,
             source_container_id,region,config_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (job_id, "queued", "queued", 0, "Migration queued.", utc_now(), utc_now(),
                  body["sourceConnectionId"], body["containerId"], body["region"], json.dumps(config)))
        threading.Thread(target=_migration_worker, args=(job_id,), daemon=True).start()
        return jsonify({"ok": True, "job": _job_public(_get_job(job_id))}), 202
    except Exception as exc:
        return jsonify({"ok": False, "error": _client_error(exc, "source validation / sts:GetCallerIdentity")}), 400


@bp.get("/jobs/<job_id>")
def get_migration_job(job_id):
    job = _get_job(job_id)
    if not job:
        return _json_error("Migration job not found.", 404, "JOB_NOT_FOUND")
    return jsonify({"ok": True, "job": _job_public(job)})


@bp.get("/jobs")
def list_migration_jobs():
    with _db() as conn:
        rows = conn.execute("SELECT job_id FROM cloud_migration_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify({"ok": True, "jobs": [_job_public(_get_job(r["job_id"])) for r in rows if _get_job(r["job_id"])]})


@bp.post("/jobs/<job_id>/cancel")
def cancel_migration_job(job_id):
    job = _get_job(job_id)
    if not job:
        return _json_error("Migration job not found.", 404, "JOB_NOT_FOUND")
    if job["status"] in ("succeeded", "failed", "cancelled"):
        return _json_error("This job has already completed.", 409, "JOB_ALREADY_FINISHED")
    with _CANCEL_LOCK:
        _CANCEL.add(job_id)
    _set_job(job_id, message="Cancellation requested; stopping at the next safe checkpoint.")
    return jsonify({"ok": True, "message": "Cancellation requested."}), 202


@bp.get("/jobs/<job_id>/validation")
def validate_migration_job(job_id):
    job = _get_job(job_id)
    if not job:
        return _json_error("Migration job not found.", 404, "JOB_NOT_FOUND")
    if not job.get("result"):
        return jsonify({"ok": True, "validated": False, "status": job["status"], "error": job.get("error")})
    result = job["result"]
    return jsonify({"ok": True, "validated": result.get("runningTaskCount", 0) >= result.get("desiredCount", 1),
                    "imageUri": result.get("imageUri"), "imageDigest": result.get("imageDigest"),
                    "runningTaskCount": result.get("runningTaskCount"), "desiredCount": result.get("desiredCount"),
                    "note": "This validates ECS task state only, not application HTTP health."})
