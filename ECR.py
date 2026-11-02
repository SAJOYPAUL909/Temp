
import os
import json
import base64
import shlex
import uuid
from io import StringIO

import boto3
import paramiko

from flask import Blueprint, request, jsonify
from botocore.exceptions import ClientError


bp = Blueprint(
    "cloud_container_migration",
    __name__,
    url_prefix="/api/cloud-container-migration"
)


# =========================================================
# COMMON HELPERS
# =========================================================

def get_body():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")

    return data


def required(data, key):
    value = data.get(key)

    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing required field: {key}")

    return str(value).strip()


def aws_clients(region):
    """
    Uses AWS credentials configured on ATM backend.

    Supported:
      AWS_ACCESS_KEY_ID
      AWS_SECRET_ACCESS_KEY
      AWS_DEFAULT_REGION
      AWS_SESSION_TOKEN (optional)
    """

    session = boto3.Session(region_name=region)

    return (
        session.client("ecr"),
        session.client("ecs"),
        session.client("sts")
    )


def error_response(exc):
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})

        return jsonify({
            "success": False,
            "error": error.get("Message", str(exc)),
            "aws_error_code": error.get("Code")
        }), 400

    return jsonify({
        "success": False,
        "error": str(exc)
    }), 400


# =========================================================
# SOURCE VM SSH
# =========================================================

def connect_source(source):

    if not isinstance(source, dict):
        raise ValueError("Source SSH details are required")

    host = required(source, "host")
    username = required(source, "username")

    port = int(source.get("port") or 22)

    client = paramiko.SSHClient()

    known_hosts = os.environ.get("ATM_SSH_KNOWN_HOSTS")

    if known_hosts:
        client.load_host_keys(known_hosts)
    else:
        client.load_system_host_keys()

    # Unknown hosts are rejected.
    client.set_missing_host_key_policy(
        paramiko.RejectPolicy()
    )

    connection_args = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": 30,
        "banner_timeout": 30,
        "auth_timeout": 30,
        "look_for_keys": False,
        "allow_agent": False
    }

    if source.get("private_key"):

        key_text = source["private_key"]
        passphrase = source.get("private_key_passphrase")

        key = None

        for key_type in (
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey
        ):
            try:
                key = key_type.from_private_key(
                    StringIO(key_text),
                    password=passphrase
                )
                break
            except Exception:
                continue

        if key is None:
            raise ValueError(
                "Unable to load SSH private key"
            )

        connection_args["pkey"] = key

    elif source.get("password"):

        connection_args["password"] = source["password"]

    else:
        raise ValueError(
            "Provide SSH password or private_key"
        )

    client.connect(**connection_args)

    return client


def remote_command(ssh, command, timeout=180):

    stdin, stdout, stderr = ssh.exec_command(
        command,
        timeout=timeout
    )

    stdin.close()

    output = stdout.read().decode(
        "utf-8",
        errors="replace"
    )

    error = stderr.read().decode(
        "utf-8",
        errors="replace"
    )

    exit_code = stdout.channel.recv_exit_status()

    if exit_code != 0:
        raise RuntimeError(
            (error or output or "Remote command failed")[-5000:]
        )

    return output


# =========================================================
# DETECT SOURCE CONTAINER RUNTIME
# =========================================================

def detect_runtime(ssh):

    command = """
    if command -v docker >/dev/null 2>&1; then
        echo docker
    elif command -v podman >/dev/null 2>&1; then
        echo podman
    else
        echo NOT_FOUND
    fi
    """

    output = remote_command(ssh, command, 30).strip()

    runtime = output.splitlines()[-1]

    if runtime not in ("docker", "podman"):
        raise RuntimeError(
            "Docker or Podman was not found on source VM"
        )

    return runtime


# =========================================================
# LIST SOURCE CONTAINERS
# =========================================================

def get_source_containers(ssh):

    runtime = detect_runtime(ssh)

    command = (
        f"{runtime} ps -a --no-trunc "
        "--format '{{json .}}'"
    )

    output = remote_command(
        ssh,
        command,
        timeout=60
    )

    containers = []

    for line in output.splitlines():

        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        containers.append({
            "id": item.get("ID", ""),
            "name": (item.get("Names") or "").lstrip("/"),
            "image": item.get("Image", ""),
            "status": item.get("Status", ""),
            "state": item.get("State", ""),
            "ports": item.get("Ports", ""),
            "runtime": runtime
        })

    return runtime, containers


# =========================================================
# GET ECR REPOSITORY
# =========================================================

def get_ecr_repository(ecr, repository_name):

    try:

        result = ecr.describe_repositories(
            repositoryNames=[repository_name]
        )

        return result["repositories"][0]

    except ClientError as exc:

        code = exc.response.get("Error", {}).get("Code")

        if code == "RepositoryNotFoundException":
            raise ValueError(
                f"ECR repository '{repository_name}' does not exist. "
                "Create the repository before migration."
            )

        raise


# =========================================================
# GET TEMPORARY ECR CREDENTIALS
# =========================================================

def get_ecr_credentials(ecr, registry_id):

    result = ecr.get_authorization_token(
        registryIds=[registry_id]
    )

    authorization = result["authorizationData"][0]

    decoded = base64.b64decode(
        authorization["authorizationToken"]
    ).decode("utf-8")

    username, password = decoded.split(":", 1)

    return username, password


# =========================================================
# LOGIN TO ECR ON SOURCE VM
# =========================================================

def source_ecr_login(
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

    # Temporary ECR password is sent through SSH stdin.
    stdin.write(password + "\n")
    stdin.flush()
    stdin.channel.shutdown_write()

    output = stdout.read().decode(
        "utf-8",
        errors="replace"
    )

    error = stderr.read().decode(
        "utf-8",
        errors="replace"
    )

    exit_code = stdout.channel.recv_exit_status()

    if exit_code != 0:
        raise RuntimeError(
            "ECR login failed on source VM: "
            + (error or output)[-4000:]
        )

    return True


# =========================================================
# API 1: LIST SOURCE CONTAINERS
# =========================================================

@bp.route("/containers", methods=["POST"])
def list_containers():

    ssh = None

    try:

        data = get_body()

        ssh = connect_source(data.get("source"))

        runtime, containers = get_source_containers(ssh)

        return jsonify({
            "success": True,
            "runtime": runtime,
            "total": len(containers),
            "containers": containers
        })

    except Exception as exc:
        return error_response(exc)

    finally:
        if ssh:
            ssh.close()


# =========================================================
# API 2: PUSH SOURCE VM IMAGE TO ECR
# =========================================================

@bp.route("/push-to-ecr", methods=["POST"])
def push_to_ecr():

    ssh = None

    try:

        data = get_body()

        source = data.get("source")

        container_id = required(
            data,
            "container_id"
        )

        repository_name = required(
            data,
            "ecr_repository"
        )

        region = str(
            data.get("aws_region")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "ap-south-1"
        )

        image_tag = str(
            data.get("image_tag")
            or f"migrated-{uuid.uuid4().hex[:8]}"
        ).strip()

        if (
            not image_tag
            or any(ch in image_tag for ch in ("/", ":", " "))
        ):
            raise ValueError(
                "Invalid image_tag. Use a simple tag such as latest."
            )

        # ---------------------------------------------
        # 1. AWS authentication from ATM backend
        # ---------------------------------------------

        ecr, _, sts = aws_clients(region)

        identity = sts.get_caller_identity()

        account_id = identity["Account"]

        repository = get_ecr_repository(
            ecr,
            repository_name
        )

        registry = repository["repositoryUri"].split("/")[0]

        image_uri = (
            f"{repository['repositoryUri']}:{image_tag}"
        )

        username, password = get_ecr_credentials(
            ecr,
            repository.get("registryId", account_id)
        )

        # ---------------------------------------------
        # 2. Connect to source VM
        # ---------------------------------------------

        ssh = connect_source(source)

        runtime = detect_runtime(ssh)

        # ---------------------------------------------
        # 3. Inspect selected container
        # ---------------------------------------------

        inspect_output = remote_command(
            ssh,
            (
                f"{runtime} inspect "
                f"{shlex.quote(container_id)}"
            ),
            timeout=60
        )

        inspected = json.loads(inspect_output)

        if not inspected:
            raise ValueError(
                "Selected container was not found"
            )

        container_info = inspected[0]

        # Prefer immutable image ID.
        source_image = (
            container_info.get("Image")
            or container_info.get("ImageName")
            or (container_info.get("Config") or {}).get("Image")
        )

        if not source_image:
            raise ValueError(
                "Unable to identify the source container image"
            )

        container_name = (
            container_info.get("Name") or container_id
        ).lstrip("/")

        # ---------------------------------------------
        # 4. Login to ECR on source VM
        # ---------------------------------------------

        source_ecr_login(
            ssh,
            runtime,
            registry,
            username,
            password
        )

        # ---------------------------------------------
        # 5. Tag image on source VM
        # ---------------------------------------------

        remote_command(
            ssh,
            (
                f"{runtime} tag "
                f"{shlex.quote(source_image)} "
                f"{shlex.quote(image_uri)}"
            ),
            timeout=120
        )

        # ---------------------------------------------
        # 6. Push image directly from source VM to ECR
        # ---------------------------------------------

        push_output = remote_command(
            ssh,
            (
                f"{runtime} push "
                f"{shlex.quote(image_uri)}"
            ),
            timeout=int(
                os.environ.get(
                    "ATM_IMAGE_PUSH_TIMEOUT",
                    "7200"
                )
            )
        )

        # ---------------------------------------------
        # 7. Logout from ECR
        # ---------------------------------------------

        try:

            remote_command(
                ssh,
                (
                    f"{runtime} logout "
                    f"{shlex.quote(registry)}"
                ),
                timeout=60
            )

        except Exception:
            pass

        return jsonify({

            "success": True,

            "message": "Image pushed successfully to ECR",

            "source": {
                "container_id": container_id,
                "container_name": container_name,
                "source_image": source_image,
                "runtime": runtime
            },

            "ecr": {
                "repository": repository_name,
                "registry": registry,
                "image_tag": image_tag,
                "image_uri": image_uri,
                "region": region
            },

            "push_output": push_output[-4000:]

        })

    except Exception as exc:
        return error_response(exc)

    finally:
        if ssh:
            ssh.close()


# =========================================================
# ECS HELPERS
# =========================================================

def create_ecs_task_definition(ecs, data, image_uri, region):

    family = required(data, "task_family")

    execution_role = required(
        data,
        "execution_role_arn"
    )

    container_name = str(
        data.get("container_name") or "app"
    ).strip()

    container = {
        "name": container_name,
        "image": image_uri,
        "essential": True
    }

    # Port mapping
    port = data.get("container_port")

    if port not in (None, ""):

        port = int(port)

        if port < 1 or port > 65535:
            raise ValueError("Invalid container_port")

        container["portMappings"] = [{
            "containerPort": port,
            "protocol": str(
                data.get("protocol") or "tcp"
            ).lower()
        }]

    # Environment variables
    environment = data.get("environment")

    if environment:

        if not isinstance(environment, dict):
            raise ValueError(
                "environment must be a JSON object"
            )

        container["environment"] = [
            {
                "name": str(key),
                "value": str(value)
            }
            for key, value in environment.items()
        ]

    # CloudWatch logs
    if data.get("log_group"):

        container["logConfiguration"] = {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": str(data["log_group"]),
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

    result = ecs.register_task_definition(
        **task_args
    )

    return result["taskDefinition"]["taskDefinitionArn"]


# =========================================================
# API 3: CREATE OR UPDATE ECS SERVICE
# =========================================================

@bp.route("/create-ecs", methods=["POST"])
def create_ecs():

    try:

        data = get_body()

        region = str(
            data.get("aws_region")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "ap-south-1"
        )

        image_uri = required(
            data,
            "image_uri"
        )

        cluster = required(
            data,
            "ecs_cluster"
        )

        service_name = required(
            data,
            "ecs_service"
        )

        ecr, ecs, sts = aws_clients(region)

        # Verify AWS identity.
        identity = sts.get_caller_identity()

        # Validate ECS cluster.
        cluster_result = ecs.describe_clusters(
            clusters=[cluster]
        )

        clusters = cluster_result.get("clusters", [])

        if not clusters or clusters[0].get("status") == "INACTIVE":
            raise ValueError(
                f"ECS cluster '{cluster}' does not exist or is inactive"
            )

        # Validate subnet and security group input.
        subnets = data.get("subnets")
        security_groups = data.get("security_groups")

        if not isinstance(subnets, list) or not subnets:
            raise ValueError(
                "Provide at least one existing subnet"
            )

        if (
            not isinstance(security_groups, list)
            or not security_groups
        ):
            raise ValueError(
                "Provide at least one existing security group"
            )

        public_ip = str(
            data.get("assign_public_ip") or "DISABLED"
        ).upper()

        if public_ip not in ("ENABLED", "DISABLED"):
            raise ValueError(
                "assign_public_ip must be ENABLED or DISABLED"
            )

        # ---------------------------------------------
        # 1. Register ECS task definition
        # ---------------------------------------------

        task_definition_arn = create_ecs_task_definition(
            ecs,
            data,
            image_uri,
            region
        )

        # ---------------------------------------------
        # 2. Network configuration
        # ---------------------------------------------

        network_configuration = {
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": security_groups,
                "assignPublicIp": public_ip
            }
        }

        desired_count = int(
            data.get("desired_count", 1)
        )

        if desired_count < 0:
            raise ValueError(
                "desired_count cannot be negative"
            )

        # ---------------------------------------------
        # 3. Check existing ECS service
        # ---------------------------------------------

        existing_result = ecs.describe_services(
            cluster=cluster,
            services=[service_name]
        )

        existing_services = existing_result.get(
            "services", []
        )

        failures = existing_result.get("failures", [])

        # If service does not exist, create it.
        if not existing_services:

            if failures:
                raise ValueError(
                    "Unable to inspect ECS service: "
                    + json.dumps(failures)
                )

            result = ecs.create_service(
                cluster=cluster,
                serviceName=service_name,
                taskDefinition=task_definition_arn,
                desiredCount=desired_count,
                launchType="FARGATE",
                networkConfiguration=network_configuration,
                deploymentConfiguration={
                    "maximumPercent": 200,
                    "minimumHealthyPercent": 50
                }
            )

            action = "created"

        else:

            service = existing_services[0]

            if service.get("status") == "INACTIVE":
                raise ValueError(
                    "The existing ECS service is inactive. "
                    "Use a new service name or remove the inactive service."
                )

            result = ecs.update_service(
                cluster=cluster,
                service=service_name,
                taskDefinition=task_definition_arn,
                desiredCount=desired_count,
                networkConfiguration=network_configuration,
                forceNewDeployment=True
            )

            action = "updated"

        service_result = result["service"]

        return jsonify({

            "success": True,

            "message": (
                f"ECS service {action} successfully. "
                "Deployment has been submitted."
            ),

            "aws_account": identity.get("Account"),

            "ecs": {
                "action": action,
                "cluster": cluster,
                "service": service_name,
                "service_arn": service_result.get("serviceArn"),
                "task_definition_arn": task_definition_arn,
                "desired_count": desired_count,
                "status": service_result.get("status")
            },

            "image_uri": image_uri

        })

    except Exception as exc:
        return error_response(exc)


# =========================================================
# HEALTH API
# =========================================================

@bp.route("/health", methods=["GET"])
def health():

    try:

        region = os.environ.get(
            "AWS_DEFAULT_REGION",
            "ap-south-1"
        )

        _, _, sts = aws_clients(region)

        identity = sts.get_caller_identity()

        return jsonify({
            "success": True,
            "message": "AWS connection successful",
            "account": identity.get("Account"),
            "region": region,
            "local_docker_required": False,
            "local_podman_required": False
        })

    except Exception as exc:
        return error_response(exc)
