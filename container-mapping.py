import os
import json
import re
import shlex
import requests
import paramiko

from run_cmd import *


MAX_RETRIES = 2


# ============================================================
# SSH COMMAND
# ============================================================

def run_without_sudo_for_vm2(ssh, sudo_password, command, check_file=None):
    print("$$$ INSIDE RUN_WINDOW_SUDO_FOR_VM2")
    print(f"\nRunning command:\n{command}")

    stdin, stdout, stderr = ssh.exec_command(command)

    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")

    return out, err


# ============================================================
# LLM ROUND 1
# ============================================================

def call_llm_round1(context):

    print("$$$ INSIDE CONTAINER CALL_LLM_ROUND_1")

    api_key = os.environ.get("api_key")

    cfg = load_config(env)

    model_name = cfg.get("model_name", {})
    model_url = cfg.get("model_url", {})

    prompt = f"""
You are an expert in containerized application architecture and cloud migration.

Analyze the following RUNNING CONTAINER.

CONTAINER INFORMATION
=====================

Container Name:
{context.get("container_name")}

Container ID:
{context.get("container_id")}

Image:
{context.get("image")}

Status:
{context.get("status")}

Ports:
{context.get("ports")}

Networks:
{context.get("networks")}

Environment Variables:
{context.get("environment")}

Mounts:
{context.get("mounts")}

Processes:
{context.get("processes")}

Working Directory:
{context.get("working_directory")}

Files Present:
{context.get("files")}


YOUR TASK
=========

Identify ONLY the files and commands that are necessary to understand the
application architecture INSIDE THIS CONTAINER.

Look specifically for:

1. Application configuration
2. Application port
3. Backend/frontend configuration
4. Database connection information
5. Redis/cache configuration
6. Kafka/RabbitMQ/queue configuration
7. External API URLs
8. Service-to-service communication
9. Environment/config overrides
10. Startup commands
11. Framework information
12. Reverse proxy configuration
13. Dependency configuration

IMPORTANT:

- Return filenames only in required_files.
- Do not return directory paths in required_files.
- Prefer files actually present in the supplied file listing.
- Do not invent filenames.
- Commands must be minimal and read-only.
- Do not use destructive commands.
- Do not modify the container.
- Do not install packages.

Return ONLY valid JSON.

FORMAT:

{{
    "required_files": [
        "package.json",
        ".env",
        "application.yml"
    ],
    "extra_commands": [
        "env",
        "ps aux",
        "cat package.json"
    ]
}}
"""

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert in containerized application "
                    "architecture and migration."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }

    attempt = 0

    while attempt < MAX_RETRIES:

        try:

            print("Round 1 attempt:", attempt)

            response = requests.post(
                url=model_url,
                headers=headers,
                json=payload,
                timeout=1200
            )

            if response.status_code != 200:

                print(
                    "### LLM ROUND 1 ERROR:",
                    response.text
                )

                return {
                    "error": response.text
                }

            model_response = (
                response
                .json()["choices"][0]["message"]["content"]
            )

            print(
                "### LLM CONTAINER ROUND 1 RESPONSE:",
                model_response
            )

            json_str = clean_json_response(model_response)

            return json.loads(json_str)

        except (
            requests.exceptions.RequestException,
            json.JSONDecodeError
        ) as e:

            attempt += 1

            if attempt >= MAX_RETRIES:

                print(
                    f"Round 1 failed after {MAX_RETRIES} attempts: {e}"
                )

                return {
                    "status": "failed",
                    "error": str(e)
                }


# ============================================================
# CLEAN LLM JSON
# ============================================================

def clean_json_response(response):

    response = response.strip()

    # Remove markdown code fences
    response = re.sub(
        r"^```(?:json)?\s*",
        "",
        response,
        flags=re.IGNORECASE
    )

    response = re.sub(
        r"\s*```$",
        "",
        response
    )

    # Extract JSON object if model added text around it
    start = response.find("{")
    end = response.rfind("}")

    if start != -1 and end != -1:
        response = response[start:end + 1]

    return response.strip()


# ============================================================
# EXECUTE ROUND 1 REQUESTS
# ============================================================

def execute_llm_requests(
    llm_decision,
    ssh,
    sudo_password,
    container_name
):

    print("$$$ INSIDE EXECUTE CONTAINER LLM REQUESTS")

    collected_files = {}
    command_outputs = {}

    # --------------------------------------------------------
    # Requested files
    # --------------------------------------------------------

    for filename in llm_decision.get(
        "required_files",
        []
    ):

        if not filename:
            continue

        filename = str(filename).strip()

        print(
            f"[+] Reading container file: {filename}"
        )

        # Search for the file inside container.
        #
        # This is intentionally read-only.
        command = (
            f"docker exec {shlex.quote(container_name)} "
            f"sh -c "
            f"'find / -type f -name {shlex.quote(filename)} "
            f"2>/dev/null | head -20'"
        )

        paths, err = run_without_sudo_for_vm2(
            ssh,
            sudo_password,
            command
        )

        paths = paths.strip().splitlines()

        file_contents = {}

        for path in paths[:20]:

            path = path.strip()

            if not path:
                continue

            cat_command = (
                f"docker exec {shlex.quote(container_name)} "
                f"sh -c "
                f"'cat {shlex.quote(path)}'"
            )

            out, err = run_without_sudo_for_vm2(
                ssh,
                sudo_password,
                cat_command
            )

            file_contents[path] = out

        collected_files[filename] = file_contents

    # --------------------------------------------------------
    # Extra commands
    # --------------------------------------------------------

    for cmd in llm_decision.get(
        "extra_commands",
        []
    ):

        if not cmd:
            continue

        cmd = str(cmd).strip()

        print(
            f"[+] Executing container command: {cmd}"
        )

        docker_command = (
            f"docker exec "
            f"{shlex.quote(container_name)} "
            f"sh -c {shlex.quote(cmd)}"
        )

        out, err = run_without_sudo_for_vm2(
            ssh,
            sudo_password,
            docker_command
        )

        command_outputs[cmd] = out

    return collected_files, command_outputs


# ============================================================
# LLM ROUND 2
# ============================================================

def call_llm_round2(
    container_context,
    files,
    commands
):

    print("$$$ INSIDE CONTAINER CALL LLM ROUND 2")

    api_key = os.environ.get("api_key")

    cfg = load_config(env)

    model_name = cfg.get("model_name", {})
    model_url = cfg.get("model_url", {})

    prompt = f"""
Analyze the containerized application using ALL supplied evidence.

Return ONLY one valid JSON object.

Do NOT return markdown.
Do NOT return explanations.
Do NOT return JSON inside a code block.

The response must be directly parseable by JSON.parse().

============================================================
CONTAINER
============================================================

Container Name:
{container_context.get("container_name")}

Container ID:
{container_context.get("container_id")}

Image:
{container_context.get("image")}

Status:
{container_context.get("status")}

Host:
{container_context.get("host")}

Docker Ports:
{json.dumps(container_context.get("ports"), indent=2)}

Networks:
{json.dumps(container_context.get("networks"), indent=2)}

Environment:
{json.dumps(container_context.get("environment"), indent=2)}

Mounts:
{json.dumps(container_context.get("mounts"), indent=2)}

Processes:
{json.dumps(container_context.get("processes"), indent=2)}

Working Directory:
{container_context.get("working_directory")}

Files:
{json.dumps(container_context.get("files"), indent=2)}

REQUESTED FILE CONTENTS:
{json.dumps(files, indent=2)}

COMMAND OUTPUTS:
{json.dumps(commands, indent=2)}


============================================================
OUTPUT SCHEMA
============================================================

{{
    "About_Application": "one-line description",

    "Nodes": {{

        "frontend": {{
            "label": "Frontend",
            "tech": "Next.js",
            "port": 3000,
            "host": "127.0.0.1",
            "group": "UI"
        }},

        "backend": {{
            "label": "Backend",
            "tech": "FastAPI",
            "port": 8000,
            "host": "127.0.0.1",
            "group": "API"
        }},

        "postgres": {{
            "label": "PostgreSQL",
            "tech": "PostgreSQL",
            "port": 5432,
            "host": "postgres",
            "group": "DATABASE"
        }}
    }},

    "Connections": [
        {{
            "from": "frontend",
            "to": "backend",
            "protocol": "HTTP",
            "source": "127.0.0.1:3000",
            "target": "backend:8000"
        }}
    ]
}}


============================================================
NODE RULES
============================================================

1. Nodes MUST be a flat JSON object.

2. Every independently identifiable application/component must
   have its own node.

3. Components include:

   - Frontend
   - Backend
   - API
   - Database
   - Authentication
   - Redis
   - Kafka
   - RabbitMQ
   - Nginx
   - Reverse proxy
   - Storage
   - Microservices
   - Worker services
   - Other independently identifiable applications

4. Do NOT create generic nodes such as:

   backend
   database
   service
   api

   when the real application/service name is known.

5. Every node must contain:

   label
   tech
   port
   host
   group

6. port MUST be a JSON number when known.

7. Unknown port:

   "port": null

8. Unknown host:

   "host": "127.0.0.1"

9. Unknown technology:

   "tech": "Unknown"

10. group MUST be one of:

    UI
    API
    DATABASE
    AUTH
    CACHE
    QUEUE
    STORAGE
    PROXY
    SERVICE
    OTHER

11. Do not invent applications.

12. Do not create a node only because its name occurs
    in an environment variable.

13. A node must be supported by actual evidence.

14. If multiple processes belong to one application,
    normally represent them as one application node.

15. If multiple containers are clearly separate services,
    represent them as separate nodes.

============================================================
CONTAINER RULES
============================================================

The container itself can represent an application/service
when the container is clearly the application boundary.

Example:

container:
    enliven-ui

image:
    enliven-ui:latest

process:
    next-server

port:
    3000

Create:

"enliven_ui": {{
    "label": "enliven-ui",
    "tech": "Next.js",
    "port": 3000,
    "host": "127.0.0.1",
    "group": "UI"
}}

Do NOT create:

container -> next-server

unless the evidence shows that they are separate communicating
components.

============================================================
PORT RULES
============================================================

Use evidence in this order:

1. Docker published ports
2. Application listening ports
3. Process information
4. Configuration files
5. Environment variables

Example:

Docker:

0.0.0.0:8080->8000/tcp

The application port is:

8000

The host published port is:

8080

Do not confuse host port 8080 with container port 8000.

If representing the application node, prefer:

"port": 8000

and:

"host": "container-name"

unless the application is accessed through the host mapping.

============================================================
NETWORK RULES
============================================================

Docker network information is strong evidence.

Example:

frontend container:
    network = app-network

backend container:
    network = app-network

This alone does NOT prove:

frontend -> backend

A connection must be supported by:

- API URL
- HTTP request
- socket connection
- configuration
- environment variable
- command output
- other direct evidence

Shared Docker network alone is insufficient.

============================================================
CONNECTION RULES
============================================================

Connections MUST ALWAYS be an array.

Each connection MUST contain:

"from"
"to"
"protocol"
"source"
"target"

Every from/to value MUST exist in Nodes.

Do not use display labels when node IDs are different.

Do not create self-connections.

Do not create duplicate connections.

Do not infer connections merely because:

- containers share a network
- services are in the same docker-compose file
- one service logically depends on another
- an application contains a database dependency

============================================================
DATABASE RULE
============================================================

If evidence contains:

DATABASE_URL=postgresql://postgres:5432/appdb

and the PostgreSQL service is clearly identified:

Create:

"postgres": {{
    "label": "PostgreSQL",
    "tech": "PostgreSQL",
    "port": 5432,
    "host": "postgres",
    "group": "DATABASE"
}}

and:

{{
    "from": "application",
    "to": "postgres",
    "protocol": "PostgreSQL",
    "source": "<known application address>",
    "target": "postgres:5432"
}}

Only do this when the configuration is actually present.

============================================================
REDIS RULE
============================================================

If evidence contains:

REDIS_HOST=redis
REDIS_PORT=6379

create:

"redis": {{
    "label": "Redis",
    "tech": "Redis",
    "port": 6379,
    "host": "redis",
    "group": "CACHE"
}}

Only create the connection when the application actually
uses Redis according to the supplied evidence.

============================================================
QUEUE RULE
============================================================

For Kafka/RabbitMQ/etc.:

Create an independent node.

Example:

"kafka": {{
    "label": "Kafka",
    "tech": "Apache Kafka",
    "port": 9092,
    "host": "kafka",
    "group": "QUEUE"
}}

Create the connection only when producer/consumer configuration
or actual communication is observed.

============================================================
EVIDENCE PRIORITY
============================================================

Use this priority:

1. Docker inspect information
2. Docker published ports
3. Process information
4. Network/socket information
5. Configuration files
6. Environment variables
7. Source-code API calls
8. Dependency files
9. Command outputs

Only use reasoning to identify what the evidence represents.

Do NOT invent architecture.

============================================================
FINAL VALIDATION
============================================================

Before returning:

1. Nodes is an object.
2. Connections is an array.
3. Every connection.from exists in Nodes.
4. Every connection.to exists in Nodes.
5. No duplicate node IDs.
6. No duplicate connections.
7. No self-connections.
8. All ports are numbers or null.
9. All hosts are strings.
10. group is one of the allowed values.
11. Valid JSON.
12. No markdown.
13. No comments.
14. No trailing commas.

Return ONLY the JSON object.
"""

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert container application "
                    "architecture analyst."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }

    attempt = 0

    while attempt < MAX_RETRIES:

        try:

            print("Round 2 attempt:", attempt)

            response = requests.post(
                url=model_url,
                headers=headers,
                json=payload,
                timeout=1200
            )

            if response.status_code != 200:

                print(
                    "### LLM ROUND 2 ERROR:",
                    response.text
                )

                return {
                    "About_Application": "Unknown",
                    "Nodes": {},
                    "Connections": []
                }

            model_response = (
                response
                .json()["choices"][0]["message"]["content"]
            )

            print(
                "### CONTAINER LLM ROUND2 RAW RESPONSE:",
                model_response
            )

            json_str = clean_json_response(
                model_response
            )

            mapping = json.loads(json_str)

            # Safety normalization
            if not isinstance(
                mapping.get("Nodes"),
                dict
            ):
                mapping["Nodes"] = {}

            if not isinstance(
                mapping.get("Connections"),
                list
            ):
                mapping["Connections"] = []

            return mapping

        except (
            requests.exceptions.RequestException,
            json.JSONDecodeError
        ) as e:

            attempt += 1

            if attempt >= MAX_RETRIES:

                print(
                    f"Round 2 failed after "
                    f"{MAX_RETRIES} attempts: {e}"
                )

                return {
                    "About_Application": "Analysis failed",
                    "Nodes": {},
                    "Connections": []
                }


# ============================================================
# DOCKER DISCOVERY
# ============================================================

def discover_running_containers(
    ssh,
    sudo_password
):

    print("$$$ DISCOVERING RUNNING CONTAINERS")

    command = (
        "docker ps "
        "--format "
        "'{{.ID}}||{{.Names}}||{{.Image}}||{{.Status}}||{{.Ports}}'"
    )

    output, err = run_without_sudo_for_vm2(
        ssh,
        sudo_password,
        command
    )

    containers = []

    for line in output.strip().splitlines():

        parts = line.split("||", 4)

        if len(parts) != 5:
            continue

        container_id = parts[0].strip()
        name = parts[1].strip()
        image = parts[2].strip()
        status = parts[3].strip()
        ports = parts[4].strip()

        containers.append({
            "container_id": container_id,
            "container_name": name,
            "image": image,
            "status": status,
            "ports": ports
        })

    return containers


# ============================================================
# DOCKER INSPECT
# ============================================================

def docker_inspect_container(
    ssh,
    sudo_password,
    container_name
):

    command = (
        f"docker inspect "
        f"{shlex.quote(container_name)}"
    )

    output, err = run_without_sudo_for_vm2(
        ssh,
        sudo_password,
        command
    )

    try:

        data = json.loads(output)

        if not data:
            return {}

        return data[0]

    except json.JSONDecodeError:

        return {}


# ============================================================
# CONTAINER PROCESSES
# ============================================================

def get_container_processes(
    ssh,
    sudo_password,
    container_name
):

    command = (
        f"docker top "
        f"{shlex.quote(container_name)}"
    )

    output, err = run_without_sudo_for_vm2(
        ssh,
        sudo_password,
        command
    )

    return output


# ============================================================
# CONTAINER NETWORK
# ============================================================

def get_container_network_info(
    inspect_data
):

    network_settings = (
        inspect_data.get(
            "NetworkSettings",
            {}
        )
    )

    networks = (
        network_settings.get(
            "Networks",
            {}
        )
    )

    result = {}

    for name, data in networks.items():

        result[name] = {
            "network_id": data.get("NetworkID"),
            "ip_address": data.get("IPAddress"),
            "gateway": data.get("Gateway"),
            "mac_address": data.get("MacAddress"),
            "aliases": data.get("Aliases")
        }

    return result


# ============================================================
# ENVIRONMENT
# ============================================================

def get_container_environment(
    inspect_data
):

    config = inspect_data.get(
        "Config",
        {}
    )

    env_list = config.get(
        "Env",
        []
    )

    result = {}

    for env_item in env_list:

        if "=" not in env_item:
            continue

        key, value = env_item.split(
            "=",
            1
        )

        # Avoid exposing secrets to the LLM.
        if any(
            secret_word in key.lower()
            for secret_word in [
                "password",
                "passwd",
                "secret",
                "token",
                "api_key",
                "apikey",
                "private_key"
            ]
        ):

            result[key] = "<REDACTED>"

        else:

            result[key] = value

    return result


# ============================================================
# MOUNTS
# ============================================================

def get_container_mounts(
    inspect_data
):

    mounts = inspect_data.get(
        "Mounts",
        []
    )

    result = []

    for mount in mounts:

        result.append({
            "type": mount.get("Type"),
            "source": mount.get("Source"),
            "destination": mount.get("Destination"),
            "read_only": mount.get("RW") is False
        })

    return result


# ============================================================
# LIST APPLICATION FILES
# ============================================================

def get_container_files(
    ssh,
    sudo_password,
    container_name
):

    command = (
        f"docker exec "
        f"{shlex.quote(container_name)} "
        f"sh -c "
        f"'find /app /opt /usr/src /workspace "
        f"-maxdepth 3 -type f 2>/dev/null | head -300'"
    )

    output, err = run_without_sudo_for_vm2(
        ssh,
        sudo_password,
        command
    )

    return output


# ============================================================
# WORKING DIRECTORY
# ============================================================

def get_container_working_directory(
    inspect_data
):

    config = inspect_data.get(
        "Config",
        {}
    )

    return config.get(
        "WorkingDir"
    ) or "/"


# ============================================================
# SINGLE CONTAINER MAPPING
# ============================================================

def generate_single_container_mapping(
    ssh,
    sudo_password,
    container
):

    container_name = container["container_name"]

    print(
        "\n========================================"
    )

    print(
        "Analyzing container:",
        container_name
    )

    print(
        "========================================"
    )

    inspect_data = docker_inspect_container(
        ssh,
        sudo_password,
        container_name
    )

    if not inspect_data:

        return {
            **container,
            "mapping": {
                "About_Application":
                    "Container inspection failed",
                "Nodes": {},
                "Connections": []
            }
        }

    config = inspect_data.get(
        "Config",
        {}
    )

    state = inspect_data.get(
        "State",
        {}
    )

    # --------------------------------------------------------
    # Processes
    # --------------------------------------------------------

    processes = get_container_processes(
        ssh,
        sudo_password,
        container_name
    )

    # --------------------------------------------------------
    # Network
    # --------------------------------------------------------

    networks = get_container_network_info(
        inspect_data
    )

    # --------------------------------------------------------
    # Environment
    # --------------------------------------------------------

    environment = get_container_environment(
        inspect_data
    )

    # --------------------------------------------------------
    # Mounts
    # --------------------------------------------------------

    mounts = get_container_mounts(
        inspect_data
    )

    # --------------------------------------------------------
    # Files
    # --------------------------------------------------------

    files = get_container_files(
        ssh,
        sudo_password,
        container_name
    )

    # --------------------------------------------------------
    # Working directory
    # --------------------------------------------------------

    working_directory = (
        get_container_working_directory(
            inspect_data
        )
    )

    context = {

        "container_name":
            container_name,

        "container_id":
            container.get("container_id"),

        "image":
            container.get("image"),

        "status":
            container.get("status"),

        "host":
            "127.0.0.1",

        "ports":
            container.get("ports"),

        "networks":
            networks,

        "environment":
            environment,

        "mounts":
            mounts,

        "processes":
            processes,

        "working_directory":
            working_directory,

        "files":
            files
    }

    # ========================================================
    # ROUND 1
    # ========================================================

    try:

        llm_decision = call_llm_round1(
            context
        )

        print(
            "### CONTAINER ROUND1 DECISION:",
            llm_decision
        )

    except Exception as e:

        print(
            "Round 1 failed:",
            e
        )

        return {
            **container,
            "mapping": {
                "About_Application":
                    "Round 1 failed",
                "Nodes": {},
                "Connections": []
            }
        }

    # ========================================================
    # COLLECT FILES / COMMANDS
    # ========================================================

    try:

        requested_files, command_outputs = (
            execute_llm_requests(
                llm_decision,
                ssh,
                sudo_password,
                container_name
            )
        )

    except Exception as e:

        print(
            "File/command collection failed:",
            e
        )

        requested_files = {}
        command_outputs = {}

    # ========================================================
    # ROUND 2
    # ========================================================

    try:

        mapping = call_llm_round2(
            context,
            requested_files,
            command_outputs
        )

    except Exception as e:

        print(
            "Round 2 failed:",
            e
        )

        mapping = {
            "About_Application":
                "Analysis failed",
            "Nodes": {},
            "Connections": []
        }

    return {
        **container,
        "container_details": {
            "id": container.get("container_id"),
            "name": container_name,
            "image": container.get("image"),
            "status": container.get("status"),
            "ports": container.get("ports"),
            "networks": networks,
            "mounts": mounts
        },
        "mapping": mapping
    }


# ============================================================
# MAIN CONTAINER MAPPING
# ============================================================

def generate_container_application_mapping(
    target
):

    print(
        "========== CONTAINER APPLICATION MAPPING =========="
    )

    source_host = target.get("host")
    source_user = target.get("user")
    source_password = target.get("password")
    source_sudo = target.get("sudo_password")

    # --------------------------------------------------------
    # SSH
    # --------------------------------------------------------

    ssh = paramiko.SSHClient()

    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    ssh.connect(
        source_host,
        username=source_user,
        password=source_password
    )

    # --------------------------------------------------------
    # Discover containers
    # --------------------------------------------------------

    containers = discover_running_containers(
        ssh,
        source_sudo
    )

    print(
        "Running containers:",
        len(containers)
    )

    if not containers:

        ssh.close()

        return [
            {
                "error":
                    "No running containers found"
            }
        ]

    all_mapping_details = []

    # --------------------------------------------------------
    # Analyze each container
    # --------------------------------------------------------

    for container in containers:

        try:

            result = generate_single_container_mapping(
                ssh,
                source_sudo,
                container
            )

            all_mapping_details.append(
                result
            )

        except Exception as e:

            print(
                f"Container mapping failed for "
                f"{container.get('container_name')}: {e}"
            )

            all_mapping_details.append({
                **container,
                "mapping": {
                    "About_Application":
                        "Analysis failed",
                    "Nodes": {},
                    "Connections": []
                },
                "error": str(e)
            })

    ssh.close()

    return all_mapping_details