
"""
DB-free Flask Blueprint:
Source VM Docker/Podman -> AWS ECR -> ECS Fargate.

ATM backend requirements:
    Flask, boto3, paramiko

Source VM requirements:
    Docker or Podman, SSH access, outbound connectivity to ECR.

AWS resources expected to exist:
    ECR repository
    ECS cluster
    ECS task execution role
    Subnets
    Security groups

Register in existing Flask application:

    from cloud_container_migration import bp as cloud_container_migration_bp
    app.register_blueprint(cloud_container_migration_bp)
"""

import base64
import json
import os
import shlex
import threading
import uuid

import boto3
import paramiko

from botocore.exceptions import ClientError
from flask import Blueprint, jsonify, request


bp = Blueprint(
    "cloud_container_migration",
    __name__,
    url_prefix="/api/cloud-container-migration"
)

_MIGRATION_LOCK = threading.Lock()


class MigrationError(Exception):
    pass


# ---------------------------------------------------------
# COMMON HELPERS
# ---------------------------------------------------------

def _body():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise MigrationError("Request body must be a JSON object")

    return data


def _required(data, key):
    value = data.get(key)

    if value is None or str(value).strip() == "":
        raise MigrationError(f"Missing required field: {key}")

    return str(value).strip()


# ---------------------------------------------------------
# SOURCE VM SSH CONNECTION
# ---------------------------------------------------------

def _connect_source(source):

    if not isinstance(source, dict):
        raise MigrationError(
            "source must contain SSH connection details"
        )

    host = _required(source, "host")
    username = _required(source, "username")

    port = int(source.get("port") or 22)

    if port < 1 or port > 65535:
        raise MigrationError("Invalid SSH port")

    client = paramiko.SSHClient()

    known_hosts = os.environ.get("ATM_SSH_KNOWN_HOSTS")

    if known_hosts:
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(
            paramiko.RejectPolicy()
        )
    else:
        # Configure ATM_SSH_KNOWN_HOSTS in production.
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

    args = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": int(
            os.environ.get("ATM_SSH_TIMEOUT", "20")
        ),
        "banner_timeout": 20,
        "auth_timeout": 20,
        "look_for_keys": False,
        "allow_agent": False
    }

    if source.get("private_key"):

        from io import StringIO

        key_text = str(source["private_key"])
        key = None
        key_errors = []

        for key_type in (
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey
        ):
            try:
                key = key_type.from_private_key(
                    StringIO(key_text),
                    password=source.get(
                        "private_key_passphrase"
                    )
                )
                break

            except Exception as exc:
                key_errors.append(str(exc))

        if key is None:
            raise MigrationError(
                "Could not read SSH private key: "
                + "; ".join(key_errors[-2:])
            )

        args["pkey"] = key

    elif source.get("password"):

        args["password"] = str(source["password"])

    else:
        raise MigrationError(
            "Provide source.password or source.private_key"
        )

    client.connect(**args)

    return client


# ---------------------------------------------------------
# REMOTE COMMAND EXECUTION
# ---------------------------------------------------------

def _remote(ssh, command, timeout=180):

    stdin, stdout, stderr = ssh.exec_command(
        command,
        timeout=timeout
    )

    stdin.close()

    out = stdout.read().decode(
        "utf-8",
        errors="replace"
    )

    err = stderr.read().decode(
        "utf-8",
        errors="replace"
    )

    code = stdout.channel.recv_exit_status()

    if code != 0:
        raise MigrationError(
            (
                err
                or out
                or f"Remote command failed with exit code {code}"
            )[-6000:]
        )

    return out


# ---------------------------------------------------------
# DETECT DOCKER / PODMAN ON SOURCE VM
# ---------------------------------------------------------

def _runtime(ssh):

    command = (
        "if command -v docker >/dev/null 2>&1; "
        "then echo docker; "
        "elif command -v podman >/dev/null 2>&1; "
        "then echo podman; "
        "else exit 127; fi"
    )

    out = _remote(ssh, command, 20)

    runtime = out.strip().splitlines()[-1]

    if runtime not in ("docker", "podman"):
        raise MigrationError(
            "Docker or Podman was not found on source VM"
        )

    return runtime


# ---------------------------------------------------------
# LIST SOURCE CONTAINERS
# ---------------------------------------------------------

def _list_containers(ssh):

    runtime = _runtime(ssh)

    command = (
        f"{runtime} ps -a --no-trunc "
        "--format '{{json .}}'"
    )

    raw = _remote(ssh, command, 60)

    rows = []

    for line in raw.splitlines():

        try:
            item = json.loads(line)

        except json.JSONDecodeError:
            continue

        rows.append({
            "id": item.get("ID", ""),
            "name": (
                item.get("Names") or ""
            ).lstrip("/"),
            "image": item.get("Image", ""),
            "status": item.get("Status", ""),
            "state": item.get("State", ""),
            "ports": item.get("Ports", ""),
            "runtime": runtime
        })

    return runtime, rows


# ---------------------------------------------------------
# AWS CLIENTS
# ---------------------------------------------------------

def _aws(region):

    session = boto3.Session(
        region_name=region
    )

    return (
        session.client("ecr"),
        session.client("ecs"),
        session.client("sts")
    )


# ---------------------------------------------------------
# VERIFY EXISTING ECR REPOSITORY
# ---------------------------------------------------------

def _existing_repository(ecr, name):

    try:

        result = ecr.describe_repositories(
            repositoryNames=[name]
        )

    except ClientError as exc:

        if (
            exc.response.get("Error", {}).get("Code")
            == "RepositoryNotFoundException"
        ):
            raise MigrationError(
                f"ECR repository '{name}' does not exist. "
                "Create it first."
            )

        raise

    return result["repositories"][0]


# ---------------------------------------------------------
# GET TEMPORARY ECR LOGIN CREDENTIALS
# ---------------------------------------------------------

def _ecr_login_details(ecr, registry_id):

    auth = ecr.get_authorization_token(
        registryIds=[registry_id]
    )["authorizationData"][0]

    decoded = base64.b64decode(
        auth["authorizationToken"]
    ).decode("utf-8")

    username, password = decoded.split(":", 1)

    return username, password


# ---------------------------------------------------------
# LOGIN TO ECR FROM SOURCE VM
# ---------------------------------------------------------

def _remote_login(
    ssh,
    runtime,
    registry,
    username,
    password
):

    command = (
        f"{runtime} login "
        f"--username {shlex.quote(username)} "
        f"--password-stdin "
        f"{shlex.quote(registry)}"
    )

    stdin, stdout, stderr = ssh.exec_command(
        command,
        timeout=90
    )

    # Password is sent through SSH stdin,
    # not exposed in the command arguments.
    stdin.write(password + "\n")
    stdin.flush()
    stdin.channel.shutdown_write()

    out = stdout.read().decode(
        "utf-8",
        errors="replace"
    )

    err = stderr.read().decode(
        "utf-8",
        errors="replace"
    )

    code = stdout.channel.recv_exit_status()

    if code != 0:
        raise MigrationError(
            "Source VM ECR login failed: "
            + (err or out)[-4000:]
        )

    return (out or err).strip()


# ---------------------------------------------------------
# TAG AND PUSH IMAGE FROM SOURCE VM DIRECTLY TO ECR
# ---------------------------------------------------------

def _push_source_image(
    ssh,
    runtime,
    source_image,
    target_image,
    registry,
    username,
    password
):

    _remote_login(
        ssh,
        runtime,
        registry,
        username,
        password
    )

    try:

        # Tag source image with ECR destination.
        _remote(
            ssh,
            (
                f"{runtime} tag "
                f"{shlex.quote(source_image)} "
                f"{shlex.quote(target_image)}"
            ),
            120
        )

        # Push directly from source VM to AWS ECR.
        output = _remote(
            ssh,
            (
                f"{runtime} push "
                f"{shlex.quote(target_image)}"
            ),
            int(
                os.environ.get(
                    "ATM_IMAGE_PUSH_TIMEOUT",
                    "7200"
                )
            )
        )

        return output[-4000:]

    finally:

        # Remove temporary registry login.
        try:

            _remote(
                ssh,
                (
                    f"{runtime} logout "
                    f"{shlex.quote(registry)}"
                ),
                60
            )

        except Exception:
            pass


# ---------------------------------------------------------
# ECS TASK DEFINITION AND SERVICE DEPLOYMENT
# ---------------------------------------------------------

def _deploy_ecs(data, image_uri, region):

    _, ecs, _ = _aws(region)

    cluster = _required(data, "ecs_cluster")
    service_name = _required(data, "ecs_service")

    family = str(
        data.get("task_family") or service_name
    ).strip()

    execution_role = _required(
        data,
        "execution_role_arn"
    )

    subnets = data.get("subnets")
    security_groups = data.get("security_groups")

    if (
        not isinstance(subnets, list)
        or not subnets
        or not all(subnets)
    ):
        raise MigrationError(
            "subnets must be a non-empty list "
            "of existing subnet IDs"
        )

    if (
        not isinstance(security_groups, list)
        or not security_groups
        or not all(security_groups)
    ):
        raise MigrationError(
            "security_groups must be a non-empty list "
            "of existing security group IDs"
        )

    container_name = str(
        data.get("container_name") or "app"
    ).strip()

    container = {
        "name": container_name,
        "image": image_uri,
        "essential": True
    }

    port = data.get("container_port")

    if port not in (None, ""):

        port = int(port)

        if port < 1 or port > 65535:
            raise MigrationError(
                "container_port must be between 1 and 65535"
            )

        container["portMappings"] = [{
            "containerPort": port,
            "protocol": str(
                data.get("protocol") or "tcp"
            ).lower()
        }]

    if data.get("environment"):

        if not isinstance(data["environment"], dict):
            raise MigrationError(
                "environment must be a JSON object "
                "of name/value pairs"
            )

        container["environment"] = [
            {
                "name": str(k),
                "value": str(v)
            }
            for k, v in data["environment"].items()
        ]

    if data.get("log_group"):

        container["logConfiguration"] = {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": str(
                    data["log_group"]
                ),
                "awslogs-region": region,
                "awslogs-stream-prefix": str(
                    data.get("log_stream_prefix") or "ecs"
                )
            }
        }

    task_args = {
        "family": family,
        "networkMode": "awsvpc",
        "requiresCompatibilities": ["FARGATE"],
        "cpu": str(data.get("task_cpu") or "512"),
        "memory": str(data.get("task_memory") or "1024"),
        "executionRoleArn": execution_role,
        "containerDefinitions": [container]
    }

    if data.get("task_role_arn"):

        task_args["taskRoleArn"] = str(
            data["task_role_arn"]
        )

    # Register new revision of task definition.
    registered = ecs.register_task_definition(
        **task_args
    )

    task_arn = registered[
        "taskDefinition"
    ]["taskDefinitionArn"]

    desired = int(data.get("desired_count", 1))

    if desired < 0:
        raise MigrationError(
            "desired_count cannot be negative"
        )

    public_ip = str(
        data.get("assign_public_ip", "DISABLED")
    ).upper()

    if public_ip not in ("ENABLED", "DISABLED"):
        raise MigrationError(
            "assign_public_ip must be ENABLED or DISABLED"
        )

    network = {
        "awsvpcConfiguration": {
            "subnets": subnets,
            "securityGroups": security_groups,
            "assignPublicIp": public_ip
        }
    }

    found = ecs.describe_services(
        cluster=cluster,
        services=[service_name]
    ).get("services", [])

    if (
        found
        and found[0].get("status") != "INACTIVE"
    ):

        result = ecs.update_service(
            cluster=cluster,
            service=service_name,
            taskDefinition=task_arn,
            desiredCount=desired,
            networkConfiguration=network,
            forceNewDeployment=True
        )

        action = "updated"

    else:

        result = ecs.create_service(
            cluster=cluster,
            serviceName=service_name,
            taskDefinition=task_arn,
            desiredCount=desired,
            launchType="FARGATE",
            networkConfiguration=network,
            deploymentConfiguration={
                "maximumPercent": 200,
                "minimumHealthyPercent": 50
            }
        )

        action = "created"

    svc = result["service"]

    return {
        "action": action,
        "cluster": cluster,
        "service": service_name,
        "service_arn": svc.get("serviceArn"),
        "task_definition_arn": task_arn,
        "desired_count": desired,
        "status": svc.get("status")
    }


# ---------------------------------------------------------
# ERROR RESPONSE
# ---------------------------------------------------------

def _error_response(exc):

    if isinstance(exc, ClientError):

        err = exc.response.get("Error", {})

        return jsonify({
            "success": False,
            "error": err.get("Message", str(exc)),
            "aws_error_code": err.get("Code")
        }), 400

    return jsonify({
        "success": False,
        "error": str(exc)
    }), 400


# ---------------------------------------------------------
# HEALTH API
# ---------------------------------------------------------

@bp.get("/health")
def health():

    try:

        region = os.environ.get(
            "AWS_DEFAULT_REGION",
            "ap-south-1"
        )

        _, _, sts = _aws(region)

        identity = sts.get_caller_identity()

        return jsonify({
            "success": True,
            "local_container_runtime_required": False,
            "aws_region": region,
            "aws_account": identity.get("Account")
        })

    except Exception as exc:

        return _error_response(exc)


# ---------------------------------------------------------
# LIST SOURCE CONTAINERS API
# ---------------------------------------------------------

@bp.post("/containers")
def containers():

    try:

        data = _body()

        ssh = _connect_source(
            data.get("source")
        )

        try:

            runtime, rows = _list_containers(ssh)

        finally:

            ssh.close()

        return jsonify({
            "success": True,
            "runtime": runtime,
            "containers": rows
        })

    except Exception as exc:

        return _error_response(exc)


# ---------------------------------------------------------
# MIGRATE IMAGE AND DEPLOY TO ECS API
# ---------------------------------------------------------

@bp.post("/migrate-and-deploy")
def migrate_and_deploy():

    if not _MIGRATION_LOCK.acquire(blocking=False):

        return jsonify({
            "success": False,
            "error": (
                "Another migration is currently running "
                "on this backend process."
            )
        }), 409

    ssh = None

    try:

        data = _body()

        source = data.get("source")

        container_id = _required(
            data,
            "container_id"
        )

        repository_name = _required(
            data,
            "ecr_repository"
        )

        region = str(
            data.get("aws_region")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "ap-south-1"
        )

        tag = str(
            data.get("image_tag")
            or f"migrated-{uuid.uuid4().hex[:8]}"
        ).strip()

        if (
            not tag
            or any(ch in tag for ch in ("/", ":", " "))
        ):
            raise MigrationError(
                "image_tag must be a simple tag, "
                "e.g. latest or release-1"
            )

        # -------------------------------------------------
        # 1. Validate ECR repository and AWS identity
        # -------------------------------------------------

        ecr, _, sts = _aws(region)

        repo = _existing_repository(
            ecr,
            repository_name
        )

        account_id = sts.get_caller_identity()["Account"]

        registry = repo[
            "repositoryUri"
        ].split("/", 1)[0]

        image_uri = (
            f"{repo['repositoryUri']}:{tag}"
        )

        username, password = _ecr_login_details(
            ecr,
            account_id
        )

        # -------------------------------------------------
        # 2. Connect to source VM
        # -------------------------------------------------

        ssh = _connect_source(source)

        runtime = _runtime(ssh)

        # -------------------------------------------------
        # 3. Inspect selected container
        # -------------------------------------------------

        inspect_raw = _remote(
            ssh,
            (
                f"{runtime} inspect "
                f"{shlex.quote(container_id)}"
            ),
            60
        )

        try:

            inspected = json.loads(inspect_raw)

        except json.JSONDecodeError:

            raise MigrationError(
                "Could not parse container inspect response "
                "from source VM"
            )

        if not inspected:

            raise MigrationError(
                "Selected container was not found on source VM"
            )

        info = inspected[0]

        source_image = (
            (info.get("Config") or {}).get("Image")
            or info.get("ImageName")
            or info.get("Image")
        )

        if not source_image:

            raise MigrationError(
                "Could not determine source image name "
                "from container inspect"
            )

        source_name = (
            info.get("Name") or container_id
        ).lstrip("/")

        # -------------------------------------------------
        # 