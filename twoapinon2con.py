import os
import re
import json
import time
import uuid
import base64
import shlex
import requests
import paramiko

from flask import Blueprint, request, jsonify

from db import load_config


# ============================================================
# BLUEPRINT
# ============================================================

bp = Blueprint(
    "non_container_to_container",
    __name__
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_CONTAINERIZATION_ATTEMPTS = 5
CONTAINER_START_WAIT = 8
LLM_TIMEOUT = 1200

ENVIRONMENT = os.environ.get("environment") or "local"


# ============================================================
# TEMPORARY MIGRATION SESSION STORAGE
# ============================================================

# Stores target connection details so that the UI only needs
# to send migration_id when submitting an edited Containerfile.
#
# For production / multi-instance Flask deployment, move this
# to PostgreSQL or Redis.

MIGRATION_SESSIONS = {}


# ============================================================
# COMMON HELPERS
# ============================================================

def print_step(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def safe_str(value):
    if value is None:
        return ""

    return str(value)


def ssh_exec(ssh, command, timeout=120):
    """
    Execute command on remote machine.

    Returns:
        stdout
        stderr
        exit_code
    """

    print(f"\n[REMOTE COMMAND]\n{command}")

    stdin, stdout, stderr = ssh.exec_command(
        command,
        timeout=timeout
    )

    out = stdout.read().decode(
        "utf-8",
        errors="ignore"
    )

    err = stderr.read().decode(
        "utf-8",
        errors="ignore"
    )

    exit_code = stdout.channel.recv_exit_status()

    print(f"[EXIT CODE] {exit_code}")

    if out:
        print(f"[STDOUT]\n{out}")

    if err:
        print(f"[STDERR]\n{err}")

    return out, err, exit_code


def connect_ssh(
    host,
    username,
    password,
    port=22
):
    ssh = paramiko.SSHClient()

    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    ssh.connect(
        hostname=host,
        username=username,
        password=password,
        port=int(port),
        timeout=30,
        banner_timeout=30,
        auth_timeout=30
    )

    return ssh


# ============================================================
# LLM CONFIGURATION
# ============================================================

def get_llm_config():

    config = load_config(
        ENVIRONMENT
    )

    model_name = (
        config.get("model_name")
        or config.get("model")
        or os.environ.get("MODEL_NAME")
    )

    model_url = (
        config.get("model_url")
        or config.get("url")
        or os.environ.get("MODEL_URL")
    )

    api_key = (
        config.get("api_key")
        or config.get("API_KEY")
        or os.environ.get("API_KEY")
    )

    if not model_url:
        raise ValueError(
            "LLM model_url is not configured"
        )

    return {
        "model_name": model_name,
        "model_url": model_url,
        "api_key": api_key
    }


def call_llm(prompt):

    llm = get_llm_config()

    headers = {
        "Content-Type": "application/json"
    }

    if llm["api_key"]:
        headers["x-api-key"] = llm["api_key"]

    payload = {
        "model": llm["model_name"],
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0
    }

    last_error = None

    for attempt in range(1, 3):

        try:

            print_step(
                f"LLM CALL {attempt}"
            )

            response = requests.post(
                llm["model_url"],
                headers=headers,
                json=payload,
                timeout=LLM_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            if "choices" in data:

                content = (
                    data["choices"][0]
                    ["message"]
                    ["content"]
                )

            elif "content" in data:

                content = data["content"]

            elif "response" in data:

                content = data["response"]

            else:

                content = str(data)

            return safe_str(
                content
            ).strip()

        except Exception as exc:

            last_error = str(exc)

            print(
                f"LLM error: {last_error}"
            )

            if attempt < 2:
                time.sleep(2)

    raise RuntimeError(
        f"LLM call failed: {last_error}"
    )


# ============================================================
# CONTAINERFILE CLEANING
# ============================================================

def clean_containerfile_response(
    content
):

    content = safe_str(
        content
    ).strip()

    # Remove ```dockerfile
    content = re.sub(
        r"^```(?:dockerfile|Dockerfile|containerfile)?\s*",
        "",
        content,
        flags=re.IGNORECASE
    )

    # Remove closing ```
    content = re.sub(
        r"\s*```$",
        "",
        content
    )

    return content.strip()


# ============================================================
# INITIAL CONTAINERFILE PROMPT
# ============================================================

def build_initial_containerfile_prompt(
    context
):

    return f"""
You are an expert Linux application migration and
containerization engineer.

Your task is to generate a production-ready
Containerfile/Dockerfile for a NON-CONTAINERIZED
Linux application.

Return ONLY the raw Containerfile content.

Do NOT:
- return Markdown
- use ```dockerfile
- provide explanations
- provide JSON
- provide text outside the Containerfile

============================================================
APPLICATION INFORMATION
============================================================

Process Information:
{context.get("process_info", "")}

Working Directory:
{context.get("working_directory", "")}

Detected Listening Port:
{context.get("port", "")}

Detected Technology:
{context.get("technology", "")}

Application Files:
{json.dumps(context.get("files", []), indent=2)}

Command Outputs:
{json.dumps(context.get("commands", {}), indent=2)}

============================================================
GENERAL RULES
============================================================

1. Identify the actual application technology from evidence.

2. Select an appropriate stable base image.

3. Do not blindly use Alpine.

4. Do not copy:
   - .git
   - .env
   - node_modules
   - venv
   - .venv
   - __pycache__
   - logs
   - temporary files
   - SSH keys
   - credentials
   - secrets

5. Use WORKDIR.

6. Use explicit COPY instructions.

7. Do not copy the host virtual environment.

8. Application must run in foreground.

9. Application should listen on 0.0.0.0.

10. Use the detected application port where applicable.

11. Do not hard-code an unrelated port.

12. Do not use host networking.

13. Do not use privileged mode.

14. Do not expose secrets through ENV.

15. Prefer a non-root runtime user where practical.

16. The final CMD/ENTRYPOINT must actually start
    the application.

17. Do not invent files, dependencies, ports or
    startup commands without evidence.

============================================================
PYTHON
============================================================

If Python:

- Use a compatible Python version.
- Prefer requirements.txt if present.
- Install requirements.
- Do not copy venv/.venv.
- Determine startup command from evidence.
- Flask/FastAPI/etc. should listen on 0.0.0.0.
- Use gunicorn/uvicorn only when appropriate.

============================================================
NODE.JS
============================================================

If Node.js:

- Use compatible Node version.
- If package-lock.json exists:

  npm ci

- If npm ci specifically fails because of peer dependencies:

  npm ci --legacy-peer-deps

- If package-lock.json does not exist:

  npm install --legacy-peer-deps

- Never copy node_modules.
- Use package.json scripts where appropriate.
- Determine the correct startup command.
- Bind server to 0.0.0.0.

============================================================
JAVA
============================================================

If Java:

- Determine JAR/WAR.
- Use appropriate JRE/JDK.
- Copy actual artifact.
- Use java -jar when appropriate.
- Do not invent artifact names.

============================================================
OTHER TECHNOLOGIES
============================================================

Identify the runtime from evidence and generate the
appropriate Containerfile.

The Containerfile must be usable with:

docker build
podman build

and:

docker run
podman run

Return ONLY the raw Containerfile.
"""


def generate_initial_containerfile(
    context
):

    response = call_llm(
        build_initial_containerfile_prompt(
            context
        )
    )

    return clean_containerfile_response(
        response
    )


# ============================================================
# REPAIR CONTAINERFILE PROMPT
# ============================================================

def build_repair_prompt(
    context,
    previous_containerfile,
    failure_reason,
    build_logs="",
    container_logs="",
    container_inspect="",
    image_info="",
    attempt=1
):

    return f"""
You are an expert Linux containerization
debugging engineer.

A non-containerized Linux application was
converted into a container.

The previous Containerfile failed.

Diagnose the actual failure and generate
a corrected Containerfile.

Return ONLY the complete raw Containerfile.

Do NOT:
- return Markdown
- use ```dockerfile
- provide explanations
- provide JSON
- provide text outside the Containerfile

============================================================
REPAIR ATTEMPT
============================================================

Attempt:
{attempt}

============================================================
APPLICATION INFORMATION
============================================================

Process Information:
{context.get("process_info", "")}

Working Directory:
{context.get("working_directory", "")}

Detected Port:
{context.get("port", "")}

Technology:
{context.get("technology", "")}

Application Files:
{json.dumps(context.get("files", []), indent=2)}

Command Outputs:
{json.dumps(context.get("commands", {}), indent=2)}

============================================================
PREVIOUS CONTAINERFILE
============================================================

{previous_containerfile}

============================================================
FAILURE REASON
============================================================

{failure_reason}

============================================================
BUILD LOGS
============================================================

{build_logs}

============================================================
CONTAINER LOGS
============================================================

{container_logs}

============================================================
CONTAINER INSPECT
============================================================

{container_inspect}

============================================================
IMAGE INFORMATION
============================================================

{image_info}

============================================================
REPAIR RULES
============================================================

1. Identify the root cause from the logs.

2. Make the minimum required correction.

3. Do not randomly rewrite the application.

4. Do not invent dependencies.

5. Do not invent files.

6. Do not blindly change the base image.

7. If dependency installation failed,
   determine the correct dependency manager.

8. Node.js:
   - package-lock.json -> npm ci
   - peer dependency failure -> npm ci --legacy-peer-deps
   - no package-lock.json -> npm install --legacy-peer-deps

9. Never copy node_modules.

10. Python:
    never copy host venv/.venv.

11. Correct an incorrect startup command.

12. Application must run in foreground.

13. Application should listen on 0.0.0.0.

14. Use correct application port.

15. Do not use host networking.

16. Do not use privileged mode.

17. Do not expose secrets.

18. Keep the Containerfile compatible with Docker
    and Podman wherever possible.

19. CMD/ENTRYPOINT must actually start the application.

20. Return only the complete Containerfile.

Return ONLY the corrected Containerfile.
"""


def generate_repaired_containerfile(
    context,
    previous_containerfile,
    failure_reason,
    build_logs,
    container_logs,
    container_inspect,
    image_info,
    attempt
):

    prompt = build_repair_prompt(
        context=context,
        previous_containerfile=previous_containerfile,
        failure_reason=failure_reason,
        build_logs=build_logs,
        container_logs=container_logs,
        container_inspect=container_inspect,
        image_info=image_info,
        attempt=attempt
    )

    response = call_llm(
        prompt
    )

    return clean_containerfile_response(
        response
    )


# ============================================================
# SOURCE DISCOVERY
# ============================================================

def get_process_working_directory(
    ssh,
    pid
):

    stdout, stderr, code = ssh_exec(
        ssh,
        f"pwdx {shlex.quote(str(pid))}",
        timeout=30
    )

    if code != 0:
        raise RuntimeError(
            f"Unable to determine working directory: {stderr}"
        )

    match = re.search(
        r"\b\d+\s+(.+)",
        stdout.strip()
    )

    if not match:
        raise RuntimeError(
            f"Unable to parse pwdx output: {stdout}"
        )

    return match.group(1).strip()


def get_process_info(
    ssh,
    pid
):

    stdout, stderr, code = ssh_exec(
        ssh,
        f"ps -fp {shlex.quote(str(pid))}",
        timeout=30
    )

    return stdout.strip()


def get_application_files(
    ssh,
    working_directory
):

    command = (
        f"cd {shlex.quote(working_directory)} && "
        "find . -maxdepth 3 -type f "
        "! -path './.git/*' "
        "! -path './node_modules/*' "
        "! -path './venv/*' "
        "! -path './.venv/*' "
        "! -path './__pycache__/*' "
        "! -name '.env' "
        "| sort | head -n 500"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=60
    )

    if code != 0:
        return []

    return [
        line.strip()
        for line in stdout.splitlines()
        if line.strip()
    ]


def get_listening_ports(
    ssh,
    pid
):

    commands = [
        f"sudo ss -tunlp | grep 'pid={pid}'",
        f"ss -tunlp | grep 'pid={pid}'"
    ]

    for command in commands:

        stdout, stderr, code = ssh_exec(
            ssh,
            command,
            timeout=30
        )

        if stdout.strip():
            return stdout.strip()

    return ""


def extract_port(
    ss_output
):

    if not ss_output:
        return None

    patterns = [
        r":(\d+)\s+.*LISTEN",
        r"127\.0\.0\.1:(\d+)",
        r"0\.0\.0\.0:(\d+)",
        r"\[::\]:(\d+)",
        r"\*:(\d+)"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            ss_output,
            flags=re.IGNORECASE
        )

        if match:

            try:

                port = int(
                    match.group(1)
                )

                if 1 <= port <= 65535:
                    return port

            except Exception:
                pass

    return None


def detect_technology(
    process_info,
    files
):

    text = (
        safe_str(process_info)
        + "\n"
        + "\n".join(files)
    ).lower()

    if any(
        x in text
        for x in [
            "node",
            "npm",
            "package.json",
            "vite",
            "next"
        ]
    ):
        return "Node.js"

    if any(
        x in text
        for x in [
            "python",
            "flask",
            "fastapi",
            "django",
            "uvicorn",
            "gunicorn"
        ]
    ):
        return "Python"

    if any(
        x in text
        for x in [
            "java",
            ".jar",
            "spring"
        ]
    ):
        return "Java"

    if (
        "dotnet" in text
        or ".dll" in text
    ):
        return ".NET"

    if "php" in text:
        return "PHP"

    if "ruby" in text:
        return "Ruby"

    if (
        "go " in text
        or "golang" in text
    ):
        return "Go"

    return "Unknown"


def read_important_files(
    ssh,
    working_directory,
    files
):

    important_names = {
        "package.json",
        "package-lock.json",
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "Pipfile.lock",
        "setup.py",
        "setup.cfg",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "go.mod",
        "composer.json",
        "Gemfile",
        "Gemfile.lock",
        "vite.config.js",
        "vite.config.ts",
        "next.config.js",
        "next.config.mjs",
        "next.config.ts"
    }

    result = {}

    for relative_file in files:

        filename = os.path.basename(
            relative_file
        )

        if filename not in important_names:
            continue

        command = (
            f"cd {shlex.quote(working_directory)} && "
            f"cat -- {shlex.quote(relative_file)}"
        )

        stdout, stderr, code = ssh_exec(
            ssh,
            command,
            timeout=30
        )

        if code == 0:

            result[
                relative_file
            ] = stdout[:30000]

    return result


# ============================================================
# REMOTE FILE OPERATIONS
# ============================================================

def write_remote_file(
    ssh,
    remote_path,
    content
):

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    command = (
        f"echo {shlex.quote(encoded)} | "
        f"base64 -d > {shlex.quote(remote_path)}"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=30
    )

    if code != 0:
        raise RuntimeError(
            f"Unable to write remote file: {stderr}"
        )


def transfer_file_sftp(
    ssh,
    local_path,
    remote_path
):

    sftp = ssh.open_sftp()

    try:

        sftp.put(
            local_path,
            remote_path
        )

    finally:

        sftp.close()


def create_source_tar(
    ssh,
    working_directory,
    local_tar_path
):

    command = (
        f"cd {shlex.quote(working_directory)} && "
        "tar "
        "--exclude='.git' "
        "--exclude='.env' "
        "--exclude='node_modules' "
        "--exclude='venv' "
        "--exclude='.venv' "
        "--exclude='__pycache__' "
        "--exclude='*.log' "
        "-czf - ."
    )

    stdin, stdout, stderr = ssh.exec_command(
        command,
        timeout=300
    )

    with open(
        local_tar_path,
        "wb"
    ) as file:

        while True:

            chunk = stdout.channel.recv(
                65536
            )

            if not chunk:
                break

            file.write(chunk)

    error = stderr.read().decode(
        "utf-8",
        errors="ignore"
    )

    exit_code = (
        stdout.channel.recv_exit_status()
    )

    if exit_code != 0:

        raise RuntimeError(
     