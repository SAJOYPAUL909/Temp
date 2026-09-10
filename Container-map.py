import json
import os
import re
import shlex
import traceback
from typing import Any, Dict, List, Optional

import paramiko
from flask import Flask, jsonify, request
from openai import OpenAI


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "200000"))
MAX_FILES_PER_CONTAINER = int(os.getenv("MAX_FILES_PER_CONTAINER", "80"))
MAX_TOTAL_FILE_CHARS = int(os.getenv("MAX_TOTAL_FILE_CHARS", "250000"))

SSH_TIMEOUT = int(os.getenv("SSH_TIMEOUT", "20"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))

# Files that are generally useful for mapping applications.
INTERESTING_FILE_NAMES = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "composer.json",
    "Gemfile",
    "Gemfile.lock",
    "Cargo.toml",
    "Cargo.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "nginx.conf",
    "default.conf",
    "haproxy.cfg",
    "application.yml",
    "application.yaml",
    "application.properties",
    ".env",
    ".env.example",
}

INTERESTING_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx",
    ".py", ".java", ".kt", ".go", ".rs",
    ".php", ".rb", ".cs",
    ".json", ".yaml", ".yml", ".xml", ".properties",
    ".conf", ".cfg", ".ini",
    ".sql",
    ".sh",
}

IGNORE_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    "build",
    "target",
    "vendor",
    ".cache",
    ".venv",
    "venv",
    "coverage",
    "logs",
    "tmp",
}


# ---------------------------------------------------------------------------
# SSH helper
# ---------------------------------------------------------------------------

class SSHClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: Optional[str] = None,
        port: int = 22,
        private_key: Optional[str] = None,
        sudo_password: Optional[str] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.private_key = private_key
        self.sudo_password = sudo_password
        self.client = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": SSH_TIMEOUT,
            "banner_timeout": SSH_TIMEOUT,
            "auth_timeout": SSH_TIMEOUT,
        }

        if self.private_key:
            kwargs["key_filename"] = self.private_key
        else:
            kwargs["password"] = self.password

        self.client.connect(**kwargs)

    def close(self):
        if self.client:
            self.client.close()

    def exec(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("SSH connection is not established")

        stdin, stdout, stderr = self.client.exec_command(
            command,
            timeout=timeout,
        )

        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()

        return {
            "command": command,
            "stdout": out,
            "stderr": err,
            "exit_code": exit_code,
        }

    def read_file(self, path: str, container_id: Optional[str] = None) -> str:
        """
        Read a remote file.

        If container_id is provided, the file is read from inside the
        container using docker exec.
        """
        if container_id:
            cmd = (
                f"docker exec {shlex.quote(container_id)} "
                f"sh -c 'cat -- {shlex.quote(path)} 2>/dev/null'"
            )
        else:
            cmd = f"cat -- {shlex.quote(path)} 2>/dev/null"

        result = self.exec(cmd, timeout=30)
        if result["exit_code"] != 0:
            return ""

        return result["stdout"][:MAX_FILE_SIZE]


# ---------------------------------------------------------------------------
# Docker discovery
# ---------------------------------------------------------------------------

def detect_container_runtime(ssh: SSHClient) -> str:
    docker = ssh.exec("command -v docker")
    if docker["exit_code"] == 0:
        return "docker"

    podman = ssh.exec("command -v podman")
    if podman["exit_code"] == 0:
        return "podman"

    raise RuntimeError("Neither docker nor podman is available on remote host")


def get_running_containers(ssh: SSHClient, runtime: str) -> List[Dict[str, Any]]:
    cmd = (
        f"{runtime} ps --format "
        "'{{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Ports}}\\t{{.Status}}'"
    )

    result = ssh.exec(cmd)

    if result["exit_code"] != 0:
        raise RuntimeError(result["stderr"] or "Unable to execute container runtime")

    containers = []

    for line in result["stdout"].splitlines():
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue

        container_id, name, image, ports, status = parts

        containers.append({
            "id": container_id,
            "name": name,
            "image": image,
            "ports": ports,
            "status": status,
        })

    return containers


def inspect_container(
    ssh: SSHClient,
    runtime: str,
    container_id: str,
) -> Dict[str, Any]:
    cmd = f"{runtime} inspect {shlex.quote(container_id)}"

    result = ssh.exec(cmd)

    if result["exit_code"] != 0:
        return {}

    try:
        data = json.loads(result["stdout"])
        return data[0] if data else {}
    except json.JSONDecodeError:
        return {}


def get_container_processes(
    ssh: SSHClient,
    runtime: str,
    container_id: str,
) -> List[str]:
    result = ssh.exec(
        f"{runtime} top {shlex.quote(container_id)} -eo pid,ppid,user,args",
        timeout=30,
    )

    if result["exit_code"] != 0:
        return []

    return result["stdout"].splitlines()[:100]


def extract_container_metadata(
    ssh: SSHClient,
    runtime: str,
    container: Dict[str, Any],
) -> Dict[str, Any]:
    inspected = inspect_container(ssh, runtime, container["id"])

    config = inspected.get("Config", {})
    network = inspected.get("NetworkSettings", {})
    mounts = inspected.get("Mounts", [])
    host_config = inspected.get("HostConfig", {})

    env = config.get("Env", []) or []

    # Do not expose obvious secrets to the LLM.
    safe_env = []
    secret_words = (
        "PASSWORD",
        "PASSWD",
        "SECRET",
        "TOKEN",
        "API_KEY",
        "PRIVATE_KEY",
        "ACCESS_KEY",
        "CREDENTIAL",
    )

    for item in env:
        key = item.split("=", 1)[0]
        if any(word in key.upper() for word in secret_words):
            safe_env.append(f"{key}=<REDACTED>")
        else:
            safe_env.append(item)

    port_bindings = network.get("Ports") or {}

    mount_info = []
    for mount in mounts:
        mount_info.append({
            "type": mount.get("Type"),
            "source": mount.get("Source"),
            "destination": mount.get("Destination"),
            "read_only": mount.get("RW") is False,
        })

    networks = {}
    for name, net in (network.get("Networks") or {}).items():
        networks[name] = {
            "ip_address": net.get("IPAddress"),
            "gateway": net.get("Gateway"),
            "aliases": net.get("Aliases"),
        }

    metadata = {
        "id": container["id"],
        "name": container["name"],
        "image": container["image"],
        "status": container["status"],
        "published_ports": port_bindings,
        "command": config.get("Cmd"),
        "entrypoint": config.get("Entrypoint"),
        "working_dir": config.get("WorkingDir"),
        "environment": safe_env,
        "mounts": mount_info,
        "networks": networks,
        "restart_policy": host_config.get("RestartPolicy"),
        "labels": config.get("Labels") or {},
        "processes": get_container_processes(
            ssh,
            runtime,
            container["id"],
        ),
    }

    return metadata


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def normalize_path(path: str) -> str:
    path = path.strip()
    if not path:
        return ""

    if not path.startswith("/"):
        return ""

    return os.path.normpath(path)


def get_mount_paths(container_metadata: Dict[str, Any]) -> List[str]:
    """
    Return container-side mount destinations.
    These are important because application source code is often mounted
    into the container.
    """
    paths = []

    for mount in container_metadata.get("mounts", []):
        destination = normalize_path(mount.get("destination", ""))
        if destination:
            paths.append(destination)

    return paths


def find_files_inside_container(
    ssh: SSHClient,
    runtime: str,
    container_id: str,
    roots: List[str],
) -> List[str]:
    """
    Find likely source/config files inside a container.
    """
    if not roots:
        roots = ["/app", "/usr/src/app", "/workspace", "/opt", "/srv"]

    existing_roots = []

    for root in roots:
        check = ssh.exec(
            f"{runtime} exec {shlex.quote(container_id)} "
            f"sh -c 'test -d {shlex.quote(root)}'",
            timeout=15,
        )
        if check["exit_code"] == 0:
            existing_roots.append(root)

    if not existing_roots:
        return []

    root_args = " ".join(shlex.quote(x) for x in existing_roots)

    # Use find inside the container. Ignore large/generated directories.
    prune_parts = []
    for ignored in IGNORE_DIRS:
        prune_parts.append(
            f"-path '*/{ignored}' -prune"
        )

    prune_expression = " -o ".join(prune_parts)

    name_patterns = []
    for ext in INTERESTING_EXTENSIONS:
        name_patterns.append(f"-name '*{ext}'")

    for name in INTERESTING_FILE_NAMES:
        name_patterns.append(f"-name '{name}'")

    names_expression = " -o ".join(name_patterns)

    command = (
        f"{runtime} exec {shlex.quote(container_id)} sh -c "
        f"\"find {root_args} "
        f"\\( {prune_expression} \\) -o "
        f"\\( -type f \\( {names_expression} \\) \\) "
        f"-print 2>/dev/null | head -n {MAX_FILES_PER_CONTAINER}\""
    )

    result = ssh.exec(command, timeout=45)

    if result["exit_code"] != 0:
        return []

    return [
        x.strip()
        for x in result["stdout"].splitlines()
        if x.strip().startswith("/")
    ][:MAX_FILES_PER_CONTAINER]


def get_file_manifest(
    ssh: SSHClient,
    runtime: str,
    container_metadata: Dict[str, Any],
) -> List[Dict[str, Any]]:
    container_id = container_metadata["id"]

    roots = get_mount_paths(container_metadata)

    # If there are no mounts, common application directories are checked.
    files = find_files_inside_container(
        ssh,
        runtime,
        container_id,
        roots,
    )

    manifest = []

    for path in files:
        stat_result = ssh.exec(
            f"{runtime} exec {shlex.quote(container_id)} "
            f"sh -c 'wc -c < {shlex.quote(path)} 2>/dev/null'",
            timeout=15,
        )

        try:
            size = int(stat_result["stdout"].strip())
        except (ValueError, TypeError):
            size = None

        manifest.append({
            "path": path,
            "size": size,
            "container": container_metadata["name"],
        })

    return manifest


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def get_llm_client() -> OpenAI:
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT,
    )


def call_llm(prompt: str) -> str:
    client = get_llm_client()

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        temperature=0,
    )

    return response.choices[0].message.content or ""


PROMPT_1 = r"""
You are an application architecture analysis expert.

We have multiple RUNNING containers from one Linux host. The containers
may represent frontend applications, backend APIs, microservices, reverse
proxies, databases, message brokers, workers, caches, or supporting services.

Your task is to determine WHICH FILES should be read to build an accurate
application mapping diagram.

INPUT:
Container metadata:
{container_metadata}

File manifest:
{file_manifest}

Return ONLY valid JSON.

Required JSON:
{{
  "containers": [
    {{
      "container": "<container name>",
      "files": [
        "<exact file path from the manifest>"
      ],
      "reason": "<short reason>"
    }}
  ]
}}

RULES:
1. Select only files that exist in the supplied file manifest.
2. Do not invent paths.
3. Prefer source/config/dependency files that reveal:
   - application/framework
   - service name
   - listening ports
   - API endpoints
   - database connections
   - cache/message-broker connections
   - frontend-to-backend communication
   - service-to-service communication
   - environment/configuration
   - reverse proxy routing
   - Docker/service startup commands
4. Include package/dependency files such as package.json,
   requirements.txt, pom.xml, go.mod, etc. when present.
5. Include relevant application entry-point files.
6. Include configuration files when they reveal endpoints, ports,
   hostnames, databases, queues, or external services.
7. Avoid generated/minified/build files where possible.
8. Do not request secrets merely because they exist in an environment file.
9. Keep the selected file list focused. Prefer the smallest useful set.
10. If a container has no useful files, return an empty files array.
"""


PROMPT_2 = r"""
You are an expert application architecture mapper.

Generate an application mapping for ALL running containers using the
container metadata and selected file contents below.

Container metadata:
{container_metadata}

Selected files:
{file_contents}

Return ONLY a valid JSON object. No markdown. No explanation.

The JSON MUST have exactly these top-level keys and this order:
1. "About_Application"
2. "Nodes"
3. "Connections"

Required structure:

{{
  "About_Application": {{
    "name": "<application/system name>",
    "description": "<short description>",
    "technology": "<main technologies/frameworks>",
    "containers": ["<container1>", "<container2>"]
  }},
  "Nodes": {{
    "<unique_node_key>": "<Technology/Name on port <port> (<IP>)>"
  }},
  "Connections": [
    "<source> -> <destination>: <protocol/API/purpose>"
  ]
}}

RULES:

1. Include ALL relevant application components found across ALL running
   containers.
2. Containers can contain:
   - frontend
   - backend/API
   - microservices
   - databases
   - caches
   - message brokers
   - reverse proxies/load balancers
   - workers
   - schedulers
   - other supporting application components
3. Do NOT create a generic "backend" node when the evidence identifies
   individual backend services. Represent the actual services.
4. Include independent components even if no connection is discovered.
5. Every node key must be unique.
6. Use a meaningful node key such as:
   "frontend", "auth-service", "postgres-db", "reverse-proxy".
7. Node values MUST follow this style:
   "Technology/Name on port <port> (<IP>)"
8. If port is unknown, use "N/A".
9. If IP is unknown, use "127.0.0.1".
10. Use the container IP when known. For externally exposed host ports,
    use the published/container port information from the metadata.
11. Do not invent ports, IPs, technologies, services, or connections.
12. Infer connections only from evidence such as:
    - source code HTTP/API URLs
    - database URLs
    - Redis URLs
    - Kafka/RabbitMQ URLs
    - reverse proxy routes
    - Docker networking
    - environment/configuration
    - frontend API configuration
13. If a hostname resolves to another discovered container name, map the
    connection to that container.
14. If a connection points outside the discovered containers, you may
    represent the destination using a node such as "external-api" only
    when there is clear evidence. Otherwise do not invent a node.
15. Connections must identify source and destination and, where possible,
    the protocol/API/purpose.
16. Include connections between discovered containers.
17. Do not expose passwords, tokens, API keys, private keys, or other
    secrets in the output.
18. The output must be valid JSON and nothing else.
"""


def parse_json_response(text: str) -> Dict[str, Any]:
    """
    Handles LLMs that occasionally return ```json ... ``` despite instructions.
    """
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    # First try the whole response.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Then try to extract the first JSON object.
    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("LLM did not return valid JSON")


# ---------------------------------------------------------------------------
# Application mapping pipeline
# ---------------------------------------------------------------------------

def sanitize_for_llm(value: Any) -> Any:
    """
    Recursively remove obvious secrets from data before sending it to LLM.
    """
    if isinstance(value, dict):
        output = {}
        for key, val in value.items():
            key_upper = str(key).upper()

            if any(
                secret_word in key_upper
                for secret_word in (
                    "PASSWORD",
                    "PASSWD",
                    "SECRET",
                    "TOKEN",
                    "API_KEY",
                    "PRIVATE_KEY",
                    "ACCESS_KEY",
                    "CREDENTIAL",
                )
            ):
                output[key] = "<REDACTED>"
            else:
                output[key] = sanitize_for_llm(val)
        return output

    if isinstance(value, list):
        return [sanitize_for_llm(x) for x in value]

    return value


def build_selected_file_contents(
    ssh: SSHClient,
    runtime: str,
    containers: List[Dict[str, Any]],
    selection: Dict[str, Any],
) -> List[Dict[str, Any]]:
    container_by_name = {
        item["name"]: item
        for item in containers
    }

    output = []
    total_chars = 0

    for selected in selection.get("containers", []):
        container_name = selected.get("container")
        container = container_by_name.get(container_name)

        if not container:
            continue

        container_id = container["id"]

        for path in selected.get("files", []):
            if total_chars >= MAX_TOTAL_FILE_CHARS:
                break

            if not isinstance(path, str) or not path.startswith("/"):
                continue

            content = ssh.read_file(
                path,
                container_id=container_id,
            )

            if not content:
                continue

            remaining = MAX_TOTAL_FILE_CHARS - total_chars
            content = content[:remaining]
            total_chars += len(content)

            output.append({
                "container": container_name,
                "path": path,
                "content": content,
            })

    return output


def generate_application_mapping(
    ssh: SSHClient,
    runtime: str,
) -> Dict[str, Any]:
    containers = get_running_containers(ssh, runtime)

    if not containers:
        return {
            "About_Application": {
                "name": "No running containers",
                "description": "No running containers were found.",
                "technology": "N/A",
                "containers": [],
            },
            "Nodes": {},
            "Connections": [],
        }

    metadata = []

    for container in containers:
        metadata.append(
            extract_container_metadata(
                ssh,
                runtime,
                container,
            )
        )

    manifests = []

    for item in metadata:
        manifests.append({
            "container": item["name"],
            "files": get_file_manifest(
                ssh,
                runtime,
                item,
            ),
        })

    safe_metadata = sanitize_for_llm(metadata)

    # ---------------- Prompt 1 ----------------
    prompt1 = PROMPT_1.format(
        container_metadata=json.dumps(
            safe_metadata,
            indent=2,
        ),
        file_manifest=json.dumps(
            manifests,
            indent=2,
        ),
    )

    selection_raw = call_llm(prompt1)
    selection = parse_json_response(selection_raw)

    # ---------------- Prompt 2 ----------------
    file_contents = build_selected_file_contents(
        ssh,
        runtime,
        metadata,
        selection,
    )

    safe_file_contents = sanitize_for_llm(file_contents)

    prompt2 = PROMPT_2.format(
        container_metadata=json.dumps(
            safe_metadata,
            indent=2,
        ),
        file_contents=json.dumps(
            safe_file_contents,
            indent=2,
        ),
    )

    mapping_raw = call_llm(prompt2)
    mapping = parse_json_response(mapping_raw)

    # Validate required shape.
    if not isinstance(mapping, dict):
        raise ValueError("Application mapping is not a JSON object")

    required_keys = [
        "About_Application",
        "Nodes",
        "Connections",
    ]

    for key in required_keys:
        if key not in mapping:
            mapping[key] = (
                {} if key != "Connections" else []
            )

    # Preserve requested key order.
    mapping = {
        "About_Application": mapping.get("About_Application", {}),
        "Nodes": mapping.get("Nodes", {}),
        "Connections": mapping.get("Connections", []),
    }

    return {
        "mapping": mapping,
        "containers": safe_metadata,
        "file_selection": selection,
        "selected_file_contents": safe_file_contents,
    }


# ---------------------------------------------------------------------------
# Flask endpoint
# ---------------------------------------------------------------------------

def validate_request(data: Dict[str, Any]):
    if not data.get("host"):
        raise ValueError("host is required")

    if not data.get("username"):
        raise ValueError("username is required")

    if not data.get("password") and not data.get("private_key"):
        raise ValueError(
            "Either password or private_key is required"
        )


@app.route("/api/application-mapping/containers", methods=["POST"])
def application_mapping_endpoint():
    """
    POST /api/application-mapping/containers

    Body:
    {
      "host": "10.0.0.10",
      "port": 22,
      "username": "ubuntu",
      "password": "password",
      "sudo_password": "password",
      "private_key": "/path/to/key"
    }
    """
    ssh = None

    try:
        data = request.get_json(silent=True) or {}

        validate_request(data)

        ssh = SSHClient(
            host=data["host"],
            port=int(data.get("port", 22)),
            username=data["username"],
            password=data.get("password"),
            private_key=data.get("private_key"),
            sudo_password=data.get("sudo_password"),
        )

        ssh.connect()

        runtime = detect_container_runtime(ssh)

        result = generate_application_mapping(
            ssh,
            runtime,
        )

        return jsonify({
            "success": True,
            "runtime": runtime,
            "host": data["host"],
            **result,
        })

    except Exception as exc:
        app.logger.exception("Application mapping failed")

        return jsonify({
            "success": False,
            "error": str(exc),
            "trace": traceback.format_exc(),
        }), 500

    finally:
        if ssh:
            ssh.close()


@app.route("/api/application-mapping/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "service": "container-application-mapping",
    })
