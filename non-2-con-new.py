import os
import re
import json
import time
import uuid
import base64
import shlex
import requests
import paramiko

from db import load_config


# ============================================================
# CONFIGURATION
# ============================================================

MAX_CONTAINERIZATION_ATTEMPTS = 5
CONTAINER_START_WAIT = 8
LLM_TIMEOUT = 1200

ENVIRONMENT = os.environ.get("environment") or "local"


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
    Execute a command over SSH.
    Returns:
        stdout, stderr, exit_code
    """
    print(f"\n[REMOTE COMMAND]\n{command}")

    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)

    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")

    exit_code = stdout.channel.recv_exit_status()

    print(f"[EXIT CODE] {exit_code}")

    if out:
        print(f"[STDOUT]\n{out}")

    if err:
        print(f"[STDERR]\n{err}")

    return out, err, exit_code


def connect_ssh(host, username, password, port=22):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

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


def connect_ssh_from_config(config, prefix):
    """
    Supports keys such as:

        SourceIP
        SourceUsername
        SourcePassword
        SourcePort

    or

        TargetIP
        TargetUsername
        TargetPassword
        TargetPort
    """

    ip = (
        config.get(f"{prefix}IP")
        or config.get(f"{prefix}_IP")
        or config.get(prefix.lower() + "_ip")
    )

    username = (
        config.get(f"{prefix}Username")
        or config.get(f"{prefix}_Username")
        or config.get(prefix.lower() + "_username")
    )

    password = (
        config.get(f"{prefix}Password")
        or config.get(f"{prefix}_Password")
        or config.get(prefix.lower() + "_password")
    )

    port = (
        config.get(f"{prefix}Port")
        or config.get(f"{prefix}_Port")
        or config.get(prefix.lower() + "_port")
        or 22
    )

    if not ip or not username:
        raise ValueError(
            f"Missing {prefix} connection information"
        )

    return connect_ssh(
        ip,
        username,
        password,
        port
    )


# ============================================================
# LLM CONFIGURATION
# ============================================================

def get_llm_config():
    config = load_config(ENVIRONMENT)

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
        raise ValueError("LLM model_url is not configured")

    return {
        "model_name": model_name,
        "model_url": model_url,
        "api_key": api_key
    }


def call_llm(prompt):
    """
    Calls the configured LLM and returns raw text.
    """

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
            print_step(f"LLM CALL - ATTEMPT {attempt}")

            response = requests.post(
                llm["model_url"],
                headers=headers,
                json=payload,
                timeout=LLM_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            # OpenAI-compatible response
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]

            # Some internal APIs may return output/content directly
            elif "content" in data:
                content = data["content"]

            elif "response" in data:
                content = data["response"]

            else:
                content = str(data)

            return safe_str(content).strip()

        except Exception as exc:
            last_error = str(exc)
            print(f"LLM error: {last_error}")

            if attempt < 2:
                time.sleep(2)

    raise RuntimeError(
        f"LLM call failed after retries: {last_error}"
    )


# ============================================================
# CONTAINERFILE CLEANING
# ============================================================

def clean_containerfile_response(content):
    """
    Removes markdown fences if the LLM accidentally returns:

    ```dockerfile
    FROM python:3.11
    ...
    ```
    """

    content = safe_str(content).strip()

    content = re.sub(
        r"^```(?:dockerfile|Dockerfile|containerfile)?\s*",
        "",
        content,
        flags=re.IGNORECASE
    )

    content = re.sub(
        r"\s*```$",
        "",
        content
    )

    return content.strip()


# ============================================================
# CONTAINERFILE GENERATION PROMPT
# ============================================================

def build_initial_containerfile_prompt(context):
    return f"""
You are an expert Linux application migration and containerization engineer.

Your task is to generate a production-ready Containerfile/Dockerfile for
a NON-CONTAINERIZED application currently running on Linux.

Return ONLY the raw Containerfile content.

Do NOT:
- return Markdown
- use ```dockerfile
- provide explanations
- provide JSON
- provide comments outside the Containerfile

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

1. Identify the actual application technology from the evidence.

2. Use an appropriate stable base image.

3. Do NOT blindly use Alpine.
   Choose Debian/Ubuntu/slim/alpine only when compatible with the
   detected application.

4. Do NOT copy:
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

5. The application must run in the foreground.

6. The application must bind to:
   0.0.0.0

7. Use the detected application port where applicable.

8. Do not hard-code an unrelated port.

9. Use WORKDIR.

10. Use explicit COPY commands.

11. Do not copy the host virtual environment.

12. Do not use host networking.

13. Do not use privileged mode.

14. Do not expose secrets through ENV.

15. Prefer a non-root runtime user where practical.

16. The final CMD/ENTRYPOINT must actually start the application.

17. Do not invent files or commands that are not supported by the
    application evidence unless they are standard and necessary.

============================================================
PYTHON RULES
============================================================

If this is Python:

- Select a compatible Python version.
- Prefer requirements.txt if present.
- Install dependencies using requirements.txt.
- Do not copy the existing venv/.venv.
- Determine the correct startup command from the process information.
- Flask/FastAPI/etc. applications must bind to 0.0.0.0.
- If gunicorn/uvicorn is clearly appropriate, use it.
- Do not assume a module name without evidence.

============================================================
NODE.JS RULES
============================================================

If this is Node.js:

- Use a compatible Node version.
- If package-lock.json exists, prefer:

  npm ci

- If npm ci fails specifically because of legacy peer dependency
  conflicts, use:

  npm ci --legacy-peer-deps

- If package-lock.json does not exist, use:

  npm install --legacy-peer-deps

- Never copy node_modules.
- Use package.json scripts when appropriate.
- For production applications, prefer a production-oriented startup.
- For Vite/React frontend applications, determine whether the
  existing application is a development server or production build
  from the evidence.
- Ensure the server listens on 0.0.0.0.

============================================================
JAVA RULES
============================================================

If this is Java:

- Determine whether the application uses JAR/WAR.
- Use an appropriate JRE/JDK.
- Copy the required artifact.
- Use java -jar when supported by evidence.
- Do not invent artifact names.

============================================================
OTHER TECHNOLOGIES
============================================================

For Go, PHP, Ruby, .NET, Apache, Nginx, etc.:

- Identify the actual runtime from evidence.
- Use an appropriate official base image.
- Use the actual application startup command.
- Do not invent configuration.

============================================================
IMPORTANT
============================================================

The Containerfile must be immediately usable for:

1. docker build / podman build
2. docker run / podman run

The application must remain running after the container starts.

Return ONLY the Containerfile.
"""


def generate_initial_containerfile(context):
    response = call_llm(
        build_initial_containerfile_prompt(context)
    )

    return clean_containerfile_response(response)


# ============================================================
# RETRY / REPAIR PROMPT
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
You are an expert Linux containerization debugging engineer.

An attempt was made to containerize and run a non-containerized Linux
application.

The generated Containerfile failed.

Your job is to diagnose the failure and produce a CORRECTED Containerfile.

Return ONLY the complete raw Containerfile.

Do NOT:
- return Markdown
- use ```dockerfile
- provide explanations
- provide JSON
- provide text before or after the Containerfile

============================================================
ATTEMPT
============================================================

Current repair attempt:
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

1. Find the actual root cause.

2. Make the minimum required changes.

3. Do NOT randomly rewrite the application.

4. Do NOT invent dependencies.

5. Do NOT invent application files.

6. Do NOT blindly change the base image.

7. If dependency installation failed:
   - determine the dependency manager
   - inspect the available files
   - use the appropriate installation command.

8. If package-lock.json exists for Node:
   use npm ci.

9. If npm ci fails specifically because of peer dependencies:
   use npm ci --legacy-peer-deps.

10. If package-lock.json does not exist:
    use npm install --legacy-peer-deps.

11. Never copy node_modules.

12. For Python:
    do not copy the host venv.

13. If the startup command is incorrect:
    correct it using the process information and application files.

14. If the application exits immediately:
    make sure the main application process runs in the foreground.

15. If the application binds only to localhost:
    change it to 0.0.0.0 where the framework supports it.

16. Use the correct detected application port.

17. Do not use host networking.

18. Do not use privileged mode.

19. Do not expose credentials or secrets.

20. Keep the Containerfile buildable by both Docker and Podman
    wherever possible.

21. The final CMD/ENTRYPOINT must actually start the application.

22. Do not include Markdown.

Return ONLY the corrected Containerfile.
"""


def generate_repaired_containerfile(
    context,
    previous_containerfile,
    failure_reason,
    build_logs="",
    container_logs="",
    container_inspect="",
    image_info="",
    attempt=1
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

    response = call_llm(prompt)

    return clean_containerfile_response(response)


# ============================================================
# SOURCE APPLICATION DISCOVERY
# ============================================================

def get_process_working_directory(ssh, pid):
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


def get_process_info(ssh, pid):
    stdout, stderr, code = ssh_exec(
        ssh,
        f"ps -fp {shlex.quote(str(pid))}",
        timeout=30
    )

    return stdout.strip()


def get_application_files(ssh, working_directory):
    command = (
        f"cd {shlex.quote(working_directory)} && "
        f"find . -maxdepth 3 -type f "
        f"! -path './.git/*' "
        f"! -path './node_modules/*' "
        f"! -path './venv/*' "
        f"! -path './.venv/*' "
        f"! -path './__pycache__/*' "
        f"! -name '.env' "
        f"| sort | head -n 500"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=60
    )

    if code != 0:
        return []

    files = []

    for line in stdout.splitlines():
        line = line.strip()

        if line:
            files.append(line)

    return files


def get_listening_ports(ssh, pid):
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


def extract_port(ss_output):
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
                port = int(match.group(1))

                if 1 <= port <= 65535:
                    return port

            except Exception:
                pass

    return None


def detect_technology(process_info, files):
    text = (
        safe_str(process_info) +
        "\n" +
        "\n".join(files)
    ).lower()

    if (
        "node" in text
        or "npm" in text
        or "package.json" in text
        or "vite" in text
        or "next" in text
    ):
        return "Node.js"

    if (
        "python" in text
        or "flask" in text
        or "fastapi" in text
        or "django" in text
        or "uvicorn" in text
        or "gunicorn" in text
    ):
        return "Python"

    if (
        "java" in text
        or "jar" in text
        or "spring" in text
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

    if "go " in text or "golang" in text:
        return "Go"

    return "Unknown"


def read_important_files(ssh, working_directory, files):
    """
    Reads a limited set of important files for LLM analysis.
    """

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
        "Dockerfile",
        "Containerfile",
        "vite.config.js",
        "vite.config.ts",
        "next.config.js",
        "next.config.mjs",
        "next.config.ts"
    }

    result = {}

    for relative_file in files:

        filename = os.path.basename(relative_file)

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
            result[relative_file] = stdout[:30000]

    return result


# ============================================================
# REMOTE FILE TRANSFER
# ============================================================

def write_remote_file(ssh, remote_path, content):
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


def transfer_file_sftp(ssh, local_path, remote_path):
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
    """
    Creates tar archive on source machine,
    streams it through SSH to local machine.
    """

    command = (
        f"cd {shlex.quote(working_directory)} && "
        "tar --exclude='.git' "
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

    with open(local_tar_path, "wb") as file:
        while True:
            chunk = stdout.channel.recv(65536)

            if not chunk:
                break

            file.write(chunk)

    error = stderr.read().decode(
        "utf-8",
        errors="ignore"
    )

    exit_code = stdout.channel.recv_exit_status()

    if exit_code != 0:
        raise RuntimeError(
            f"Failed creating application archive: {error}"
        )


# ============================================================
# TARGET RUNTIME
# ============================================================

def detect_container_runtime(ssh):
    """
    Detect Docker or Podman on destination VM.
    """

    stdout, stderr, code = ssh_exec(
        ssh,
        "command -v podman || command -v docker",
        timeout=30
    )

    if code != 0:
        raise RuntimeError(
            "Neither Docker nor Podman is installed on destination VM"
        )

    path = stdout.strip().splitlines()[0]

    if "podman" in path:
        return "podman"

    if "docker" in path:
        return "docker"

    raise RuntimeError(
        f"Unsupported container runtime: {path}"
    )


def get_runtime_version(ssh, runtime):
    stdout, stderr, code = ssh_exec(
        ssh,
        f"{runtime} --version",
        timeout=30
    )

    return stdout.strip()


# ============================================================
# CONTAINER OPERATIONS
# ============================================================

def remove_container(ssh, runtime, container_name):
    command = (
        f"{runtime} rm -f "
        f"{shlex.quote(container_name)} "
        "2>/dev/null || true"
    )

    ssh_exec(
        ssh,
        command,
        timeout=60
    )


def remove_image(ssh, runtime, image_name):
    command = (
        f"{runtime} rmi -f "
        f"{shlex.quote(image_name)} "
        "2>/dev/null || true"
    )

    ssh_exec(
        ssh,
        command,
        timeout=60
    )


def build_image(
    ssh,
    runtime,
    image_name,
    working_directory
):
    command = (
        f"cd {shlex.quote(working_directory)} && "
        f"{runtime} build --no-cache "
        f"-t {shlex.quote(image_name)} "
        "."
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=1200
    )

    return {
        "success": code == 0,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": code
    }


def run_container(
    ssh,
    runtime,
    image_name,
    container_name,
    port,
    working_directory
):
    command = (
        f"{runtime} run -d "
        f"--name {shlex.quote(container_name)} "
        f"-p {int(port)}:{int(port)} "
        f"{shlex.quote(image_name)}"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=120
    )

    return {
        "success": code == 0,
        "container_id": stdout.strip(),
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": code
    }


def get_container_status(
    ssh,
    runtime,
    container_name
):
    """
    Uses inspect instead of relying only on docker ps filtering.
    """

    command = (
        f"{runtime} inspect "
        f"{shlex.quote(container_name)} "
        "2>/dev/null"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=60
    )

    if code != 0 or not stdout.strip():
        return {
            "exists": False,
            "running": False,
            "status": "not_created",
            "raw": stderr or stdout
        }

    try:
        data = json.loads(stdout)

        if not data:
            return {
                "exists": False,
                "running": False,
                "status": "not_created",
                "raw": stdout
            }

        state = data[0].get("State", {})

        return {
            "exists": True,
            "running": bool(state.get("Running")),
            "status": state.get("Status"),
            "exit_code": state.get("ExitCode"),
            "error": state.get("Error"),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "raw": data
        }

    except Exception:
        return {
            "exists": True,
            "running": False,
            "status": "unknown",
            "raw": stdout
        }


def get_container_logs(
    ssh,
    runtime,
    container_name
):
    command = (
        f"{runtime} logs --tail 300 "
        f"{shlex.quote(container_name)} "
        "2>&1"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=120
    )

    return stdout


def get_container_inspect(
    ssh,
    runtime,
    container_name
):
    command = (
        f"{runtime} inspect "
        f"{shlex.quote(container_name)} "
        "2>&1"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=60
    )

    return stdout


def check_image(
    ssh,
    runtime,
    image_name
):
    command = (
        f"{runtime} image inspect "
        f"{shlex.quote(image_name)} "
        "2>&1"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=60
    )

    return {
        "exists": code == 0,
        "raw": stdout
    }


def get_container_port_mapping(
    ssh,
    runtime,
    container_name
):
    command = (
        f"{runtime} port "
        f"{shlex.quote(container_name)} "
        "2>&1"
    )

    stdout, stderr, code = ssh_exec(
        ssh,
        command,
        timeout=30
    )

    return stdout.strip()


# ============================================================
# CONTAINERFILE TRANSFER
# ============================================================

def transfer_containerfile(
    ssh,
    target_directory,
    containerfile
):
    """
    Writes Containerfile to destination.

    Docker and Podman both understand Containerfile.
    """

    remote_path = (
        f"{target_directory}/Containerfile"
    )

    write_remote_file(
        ssh,
        remote_path,
        containerfile
    )

    # Also create Dockerfile for compatibility
    dockerfile_path = (
        f"{target_directory}/Dockerfile"
    )

    write_remote_file(
        ssh,
        dockerfile_path,
        containerfile
    )

    return remote_path


# ============================================================
# FAILURE DIAGNOSIS
# ============================================================

def diagnose_failure(
    build_result,
    run_result,
    status,
    image_info,
    container_logs,
    container_inspect
):
    if not build_result.get("success"):
        return "CONTAINER_IMAGE_BUILD_FAILED"

    if not image_info.get("exists"):
        return "IMAGE_NOT_CREATED_AFTER_BUILD"

    if not run_result.get("success"):
        return "CONTAINER_RUN_COMMAND_FAILED"

    if not status.get("exists"):
        return "CONTAINER_WAS_NOT_CREATED"

    if not status.get("running"):
        return "CONTAINER_CREATED_BUT_NOT_RUNNING"

    return "UNKNOWN_CONTAINER_FAILURE"


# ============================================================
# SINGLE BUILD/RUN ATTEMPT
# ============================================================

def execute_container_attempt(
    ssh,
    runtime,
    image_name,
    container_name,
    port,
    target_directory,
    containerfile
):
    print_step(
        f"CONTAINERIZATION ATTEMPT - {container_name}"
    )

    # --------------------------------------------------------
    # Replace Containerfile
    # --------------------------------------------------------

    transfer_containerfile(
        ssh,
        target_directory,
        containerfile
    )

    # --------------------------------------------------------
    # Remove old container
    # --------------------------------------------------------

    remove_container(
        ssh,
        runtime,
        container_name
    )

    # --------------------------------------------------------
    # Build
    # --------------------------------------------------------

    build_result = build_image(
        ssh=ssh,
        runtime=runtime,
        image_name=image_name,
        working_directory=target_directory
    )

    image_info = check_image(
        ssh,
        runtime,
        image_name
    )

    # --------------------------------------------------------
    # If build failed, do not attempt to run
    # --------------------------------------------------------

    if not build_result["success"]:
        return {
            "success": False,
            "failure_reason": "CONTAINER_IMAGE_BUILD_FAILED",
            "build": build_result,
            "run": {},
            "status": {
                "exists": False,
                "running": False,
                "status": "build_failed"
            },
            "image_info": image_info,
            "container_logs": "",
            "container_inspect": ""
        }

    # --------------------------------------------------------
    # Image was not created
    # --------------------------------------------------------

    if not image_info["exists"]:
        return {
            "success": False,
            "failure_reason": "IMAGE_NOT_CREATED_AFTER_BUILD",
            "build": build_result,
            "run": {},
            "status": {
                "exists": False,
                "running": False,
                "status": "image_missing"
            },
            "image_info": image_info,
            "container_logs": "",
            "container_inspect": ""
        }

    # --------------------------------------------------------
    # Run container
    # --------------------------------------------------------

    run_result = run_container(
        ssh=ssh,
        runtime=runtime,
        image_name=image_name,
        container_name=container_name,
        port=port,
        working_directory=target_directory
    )

    # --------------------------------------------------------
    # Give application time to start
    # --------------------------------------------------------

    time.sleep(CONTAINER_START_WAIT)

    # --------------------------------------------------------
    # Check status
    # --------------------------------------------------------

    status = get_container_status(
        ssh,
        runtime,
        container_name
    )

    # --------------------------------------------------------
    # Success
    # --------------------------------------------------------

    if (
        run_result["success"]
        and status["exists"]
        and status["running"]
    ):
        return {
            "success": True,
            "failure_reason": None,
            "build": build_result,
            "run": run_result,
            "status": status,
            "image_info": image_info,
            "container_logs": "",
            "container_inspect": ""
        }

    # --------------------------------------------------------
    # Container exists but stopped
    # --------------------------------------------------------

    container_logs = ""

    container_inspect = ""

    if status["exists"]:
        container_logs = get_container_logs(
            ssh,
            runtime,
            container_name
        )

        container_inspect = get_container_inspect(
            ssh,
            runtime,
            container_name
        )

    failure_reason = diagnose_failure(
        build_result=build_result,
        run_result=run_result,
        status=status,
        image_info=image_info,
        container_logs=container_logs,
        container_inspect=container_inspect
    )

    return {
        "success": False,
        "failure_reason": failure_reason,
        "build": build_result,
        "run": run_result,
        "status": status,
        "image_info": image_info,
        "container_logs": container_logs,
        "container_inspect": container_inspect
    }


# ============================================================
# AUTOMATIC CONTAINERIZATION WITH LLM REPAIR
# ============================================================

def build_and_run_with_repair(
    ssh,
    runtime,
    image_name,
    container_name,
    port,
    target_directory,
    context,
    initial_containerfile
):
    """
    Maximum five automatic attempts.

    Attempt 1:
        Initial LLM generated Containerfile

    Attempt 2-5:
        Failure evidence -> LLM repair -> replace Containerfile
        -> build -> run -> verify
    """

    containerfile = initial_containerfile

    attempt_history = []

    latest_result = None

    for attempt in range(1, MAX_CONTAINERIZATION_ATTEMPTS + 1):

        print_step(
            f"AUTOMATIC CONTAINERIZATION ATTEMPT "
            f"{attempt}/{MAX_CONTAINERIZATION_ATTEMPTS}"
        )

        result = execute_container_attempt(
            ssh=ssh,
            runtime=runtime,
            image_name=image_name,
            container_name=container_name,
            port=port,
            target_directory=target_directory,
            containerfile=containerfile
        )

        latest_result = result

        attempt_record = {
            "attempt": attempt,
            "failure_reason": result.get("failure_reason"),
            "success": result.get("success"),
            "status": result.get("status"),
            "build_exit_code": result.get(
                "build", {}
            ).get("exit_code"),
            "run_exit_code": result.get(
                "run", {}
            ).get("exit_code")
        }

        attempt_history.append(attempt_record)

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if result["success"]:

            return {
                "success": True,
                "attempts": attempt,
                "containerfile": containerfile,
                "attempt_history": attempt_history,
                "latest_result": result
            }

        # ----------------------------------------------------
        # Maximum attempts reached
        # ----------------------------------------------------

        if attempt >= MAX_CONTAINERIZATION_ATTEMPTS:

            return {
                "success": False,
                "attempts": attempt,
                "containerfile": containerfile,
                "attempt_history": attempt_history,
                "latest_result": result
            }

        # ----------------------------------------------------
        # Collect failure evidence
        # ----------------------------------------------------

        build_logs = (
            result.get("build", {}).get("stdout", "")
            + "\n"
            + result.get("build", {}).get("stderr", "")
        )

        run_logs = (
            result.get("run", {}).get("stdout", "")
            + "\n"
            + result.get("run", {}).get("stderr", "")
        )

        container_logs = result.get(
            "container_logs",
            ""
        )

        container_inspect = result.get(
            "container_inspect",
            ""
        )

        image_info = result.get(
            "image_info",
            {}
        )

        # Include run failure in diagnosis too
        failure_reason = (
            f"{result.get('failure_reason')}\n"
            f"Run result:\n{run_logs}"
        )

        # ----------------------------------------------------
        # Ask LLM to repair
        # ----------------------------------------------------

        print_step(
            f"LLM REPAIR FOR ATTEMPT {attempt + 1}"
        )

        try:
            repaired_containerfile = (
                generate_repaired_containerfile(
                    context=context,
                    previous_containerfile=containerfile,
                    failure_reason=failure_reason,
                    build_logs=build_logs,
                    container_logs=container_logs,
                    container_inspect=container_inspect,
                    image_info=json.dumps(
                        image_info,
                        indent=2,
                        default=str
                    ),
                    attempt=attempt + 1
                )
            )

            if not repaired_containerfile.strip():
                raise RuntimeError(
                    "LLM returned an empty Containerfile"
                )

            containerfile = repaired_containerfile

        except Exception as exc:
            print(
                f"LLM repair failed: {exc}"
            )

            return {
                "success": False,
                "attempts": attempt,
                "containerfile": containerfile,
                "attempt_history": attempt_history,
                "latest_result": result,
                "llm_error": str(exc)
            }

    return {
        "success": False,
        "attempts": MAX_CONTAINERIZATION_ATTEMPTS,
        "containerfile": containerfile,
        "attempt_history": attempt_history,
        "latest_result": latest_result
    }


# ============================================================
# MIGRATION STATE
# ============================================================

"""
Temporary in-memory migration storage.

For production, replace this with PostgreSQL/Redis.

The important point is:
the UI does NOT need to receive the SSH password.

The backend stores the connection information temporarily and
the UI only receives migration_id.
"""

MIGRATION_SESSIONS = {}


def create_migration_session(
    migration_id,
    target,
    runtime,
    image_name,
    container_name,
    port,
    target_directory
):
    MIGRATION_SESSIONS[migration_id] = {
        "migration_id": migration_id,
        "target": target,
        "runtime": runtime,
        "image_name": image_name,
        "container_name": container_name,
        "port": port,
        "target_directory": target_directory,
        "created_at": time.time()
    }


def get_migration_session(migration_id):
    return MIGRATION_SESSIONS.get(
        migration_id
    )


# ============================================================
# MAIN MIGRATION FUNCTION
# ============================================================

def migrate_non_container_application(
    source,
    target,
    pid
):
    """
    Main migration workflow.
    """

    migration_id = str(uuid.uuid4())

    source_ssh = None
    target_ssh = None

    local_tar = None

    try:

        # ====================================================
        # SOURCE CONNECTION
        # ====================================================

        print_step("CONNECTING TO SOURCE VM")

        source_ssh = connect_ssh(
            host=source["ip"],
            username=source["username"],
            password=source.get("password"),
            port=source.get("port", 22)
        )

        # ====================================================
        # DISCOVER APPLICATION
        # ====================================================

        print_step("DISCOVERING APPLICATION")

        working_directory = get_process_working_directory(
            source_ssh,
            pid
        )

        process_info = get_process_info(
            source_ssh,
            pid
        )

        files = get_application_files(
            source_ssh,
            working_directory
        )

        important_files = read_important_files(
            source_ssh,
            working_directory,
            files
        )

        port_output = get_listening_ports(
            source_ssh,
            pid
        )

        detected_port = extract_port(
            port_output
        )

        if not detected_port:
            detected_port = 8080

        technology = detect_technology(
            process_info,
            files
        )

        print_step("APPLICATION DISCOVERY RESULT")

        print(
            json.dumps(
                {
                    "working_directory": working_directory,
                    "process_info": process_info,
                    "port_output": port_output,
                    "port": detected_port,
                    "technology": technology,
                    "files": files
                },
                indent=2
            )
        )

        # ====================================================
        # LLM CONTEXT
        # ====================================================

        context = {
            "process_info": process_info,
            "working_directory": working_directory,
            "port": detected_port,
            "technology": technology,
            "files": files,
            "commands": {
                "listening_ports": port_output,
                "important_files": important_files
            }
        }

        # ====================================================
        # GENERATE INITIAL CONTAINERFILE
        # ====================================================

        print_step(
            "GENERATING INITIAL CONTAINERFILE"
        )

        containerfile = (
            generate_initial_containerfile(
                context
            )
        )

        if not containerfile.strip():
            raise RuntimeError(
                "LLM returned empty Containerfile"
            )

        print_step("GENERATED CONTAINERFILE")

        print(containerfile)

        # ====================================================
        # CREATE LOCAL TEMP ARCHIVE
        # ====================================================

        local_tar = os.path.join(
            "/tmp",
            f"migration_{migration_id}.tar.gz"
        )

        print_step(
            "CREATING APPLICATION ARCHIVE"
        )

        create_source_tar(
            source_ssh,
            working_directory,
            local_tar
        )

        # ====================================================
        # TARGET CONNECTION
        # ====================================================

        print_step("CONNECTING TO TARGET VM")

        target_ssh = connect_ssh(
            host=target["ip"],
            username=target["username"],
            password=target.get("password"),
            port=target.get("port", 22)
        )

        # ====================================================
        # DETECT DOCKER / PODMAN
        # ====================================================

        runtime = detect_container_runtime(
            target_ssh
        )

        runtime_version = get_runtime_version(
            target_ssh,
            runtime
        )

        print(
            f"Container runtime: {runtime}"
        )

        print(
            f"Runtime version: {runtime_version}"
        )

        # ====================================================
        # CONTAINER NAMES
        # ====================================================

        safe_pid = re.sub(
            r"[^a-zA-Z0-9_.-]",
            "",
            str(pid)
        )

        container_name = (
            f"migrated-app-{safe_pid}"
        )

        image_name = (
            f"migrated-app-{safe_pid}:latest"
        )

        target_user = target["username"]

        target_directory = (
            f"/home/{target_user}/"
            f"non_container_migration_{safe_pid}"
        )

        # ====================================================
        # CREATE TARGET DIRECTORY
        # ====================================================

        stdout, stderr, code = ssh_exec(
            target_ssh,
            (
                f"mkdir -p "
                f"{shlex.quote(target_directory)}"
            ),
            timeout=60
        )

        if code != 0:
            raise RuntimeError(
                f"Unable to create target directory: "
                f"{stderr}"
            )

        # ====================================================
        # TRANSFER APPLICATION ARCHIVE
        # ====================================================

        print_step(
            "TRANSFERRING APPLICATION TO TARGET"
        )

        remote_tar = (
            f"{target_directory}/application.tar.gz"
        )

        transfer_file_sftp(
            target_ssh,
            local_tar,
            remote_tar
        )

        # ====================================================
        # EXTRACT APPLICATION
        # ====================================================

        print_step(
            "EXTRACTING APPLICATION ON TARGET"
        )

        extract_command = (
            f"cd {shlex.quote(target_directory)} && "
            f"tar -xzf application.tar.gz && "
            f"rm -f application.tar.gz"
        )

        stdout, stderr, code = ssh_exec(
            target_ssh,
            extract_command,
            timeout=300
        )

        if code != 0:
            raise RuntimeError(
                f"Unable to extract application: "
                f"{stderr}"
            )

        # ====================================================
        # IMPORTANT:
        # Always overwrite Containerfile AFTER extraction.
        #
        # The source application might itself contain a
        # Dockerfile/Containerfile.
        # ====================================================

        transfer_containerfile(
            target_ssh,
            target_directory,
            containerfile
        )

        # ====================================================
        # SAVE MIGRATION SESSION
        # ====================================================

        create_migration_session(
            migration_id=migration_id,
            target=target,
            runtime=runtime,
            image_name=image_name,
            container_name=container_name,
            port=detected_port,
            target_directory=target_directory
        )

        # ====================================================
        # AUTOMATIC BUILD/RUN + LLM REPAIR
        # ====================================================

        result = build_and_run_with_repair(
            ssh=target_ssh,
            runtime=runtime,
            image_name=image_name,
            container_name=container_name,
            port=detected_port,
            target_directory=target_directory,
            context=context,
            initial_containerfile=containerfile
        )

        # ====================================================
        # SUCCESS
        # ====================================================

        if result["success"]:

            return {
                "status": "success",
                "migration_id": migration_id,
                "message": (
                    "Application successfully "
                    "containerized and running "
                    "on destination VM."
                ),
                "pid": pid,
                "container_runtime": runtime,
                "container_name": container_name,
                "image_name": image_name,
                "port": detected_port,
                "attempts": result["attempts"],
                "container_status": result[
                    "latest_result"
                ]["status"],
                "containerfile": result[
                    "containerfile"
                ],
                "attempt_history": result[
                    "attempt_history"
                ]
            }

        # ====================================================
        # FIVE ATTEMPTS FAILED
        # ====================================================

        latest = result.get(
            "latest_result",
            {}
        )

        return {
            "status": "manual_intervention_required",
            "migration_id": migration_id,
            "message": (
                "Automatic containerization failed after "
                f"{result.get('attempts', MAX_CONTAINERIZATION_ATTEMPTS)} "
                "attempts. The generated Containerfile is "
                "returned to the UI. Edit the Containerfile "
                "and submit it using "
                "/api/non-container-to-container-run-edited."
            ),
            "pid": pid,
            "container_runtime": runtime,
            "container_name": container_name,
            "image_name": image_name,
            "port": detected_port,
            "attempts": result.get(
                "attempts",
                MAX_CONTAINERIZATION_ATTEMPTS
            ),
            "containerfile": result.get(
                "containerfile",
                containerfile
            ),
            "failure_reason": latest.get(
                "failure_reason"
            ),
            "build_logs": (
                latest.get("build", {}).get(
                    "stdout", ""
                )
                + "\n"
                + latest.get("build", {}).get(
                    "stderr", ""
                )
            ),
            "container_logs": latest.get(
                "container_logs",
                ""
            ),
            "container_inspect": latest.get(
                "container_inspect",
                ""
            ),
            "image_info": latest.get(
                "image_info",
                {}
            ),
            "attempt_history": result.get(
                "attempt_history",
                []
            )
        }

    finally:

        # ====================================================
        # CLOSE SSH CONNECTIONS
        # ====================================================

        if source_ssh:
            source_ssh.close()

        if target_ssh:
            target_ssh.close()

        # ====================================================
        # REMOVE LOCAL TEMP ARCHIVE
        # ====================================================

        if local_tar and os.path.exists(local_tar):
            try:
                os.remove(local_tar)
            except Exception:
                pass


# ============================================================
# FLASK APP
# ============================================================

from flask import Flask, request, jsonify


app = Flask(__name__)


# ============================================================
# MAIN API
# ============================================================

@app.route(
    "/api/non-container-to-container-migrate",
    methods=["POST"]
)
def non_container_to_container_migrate():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        source = data.get("source", {})
        target = data.get("target", {})
        pid = data.get("pid")

        if not pid:
            return jsonify({
                "status": "error",
                "message": "pid is required"
            }), 400

        if not source.get("ip"):
            return jsonify({
                "status": "error",
                "message": "source.ip is required"
            }), 400

        if not source.get("username"):
            return jsonify({
                "status": "error",
                "message": "source.username is required"
            }), 400

        if not target.get("ip"):
            return jsonify({
                "status": "error",
                "message": "target.ip is required"
            }), 400

        if not target.get("username"):
            return jsonify({
                "status": "error",
                "message": "target.username is required"
            }), 400

        result = migrate_non_container_application(
            source=source,
            target=target,
            pid=pid
        )

        return jsonify(result), 200

    except Exception as exc:

        print_step("MIGRATION FAILED")

        import traceback
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


# ============================================================
# RUN USER-EDITED CONTAINERFILE
# ============================================================

@app.route(
    "/api/non-container-to-container-run-edited",
    methods=["POST"]
)
def run_edited_containerfile():

    """
    Called by UI after automatic 5 attempts fail.

    Expected request:

    {
        "migration_id": "...",
        "containerfile": "FROM ...",
        "port": 8015
    }

    The UI does NOT need to send SSH credentials again.
    """

    target_ssh = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        migration_id = data.get(
            "migration_id"
        )

        edited_containerfile = data.get(
            "containerfile"
        )

        if not migration_id:
            return jsonify({
                "status": "error",
                "message": "migration_id is required"
            }), 400

        if not edited_containerfile:
            return jsonify({
                "status": "error",
                "message": "containerfile is required"
            }), 400

        session = get_migration_session(
            migration_id
        )

        if not session:
            return jsonify({
                "status": "error",
                "message": (
                    "Migration session not found "
                    "or has expired."
                )
            }), 404

        # ----------------------------------------------------
        # Use UI Containerfile exactly as supplied
        # ----------------------------------------------------

        edited_containerfile = (
            clean_containerfile_response(
                edited_containerfile
            )
        )

        target = session["target"]

        target_ssh = connect_ssh(
            host=target["ip"],
            username=target["username"],
            password=target.get("password"),
            port=target.get("port", 22)
        )

        runtime = session["runtime"]

        # ----------------------------------------------------
        # Allow UI to change port if required
        # ----------------------------------------------------

        port = data.get(
            "port",
            session["port"]
        )

        try:
            port = int(port)
        except Exception:
            port = session["port"]

        image_name = session[
            "image_name"
        ]

        container_name = session[
            "container_name"
        ]

        target_directory = session[
            "target_directory"
        ]

        # ----------------------------------------------------
        # Replace Containerfile
        # ----------------------------------------------------

        transfer_containerfile(
            target_ssh,
            target_directory,
            edited_containerfile
        )

        # ----------------------------------------------------
        # Remove old container
        # ----------------------------------------------------

        remove_container(
            target_ssh,
            runtime,
            container_name
        )

        # ----------------------------------------------------
        # Build
        # ----------------------------------------------------

        build_result = build_image(
            ssh=target_ssh,
            runtime=runtime,
            image_name=image_name,
            working_directory=target_directory
        )

        image_info = check_image(
            target_ssh,
            runtime,
            image_name
        )

        # ----------------------------------------------------
        # Build failed
        # ----------------------------------------------------

        if not build_result["success"]:

            return jsonify({
                "status": "manual_retry_required",
                "message": (
                    "Edited Containerfile failed "
                    "during image build."
                ),
                "migration_id": migration_id,
                "container_runtime": runtime,
                "container_name": container_name,
                "image_name": image_name,
                "port": port,
                "containerfile": edited_containerfile,
                "build_logs": (
                    build_result.get(
                        "stdout",
                        ""
                    )
                    + "\n"
                    + build_result.get(
                        "stderr",
                        ""
                    )
                ),
                "image_info": image_info
            }), 200

        # ----------------------------------------------------
        # Image missing
        # ----------------------------------------------------

        if not image_info["exists"]:

            return jsonify({
                "status": "manual_retry_required",
                "message": (
                    "Build command completed but "
                    "the image was not found."
                ),
                "migration_id": migration_id,
                "container_runtime": runtime,
                "container_name": container_name,
                "image_name": image_name,
                "port": port,
                "containerfile": edited_containerfile,
                "build_logs": (
                    build_result.get(
                        "stdout",
                        ""
                    )
                    + "\n"
                    + build_result.get(
                        "stderr",
                        ""
                    )
                ),
                "image_info": image_info
            }), 200

        # ----------------------------------------------------
        # Run edited Containerfile
        # ----------------------------------------------------

        run_result = run_container(
            ssh=target_ssh,
            runtime=runtime,
            image_name=image_name,
            container_name=container_name,
            port=port,
            working_directory=target_directory
        )

        time.sleep(
            CONTAINER_START_WAIT
        )

        # ----------------------------------------------------
        # Check status
        # ----------------------------------------------------

        status = get_container_status(
            target_ssh,
            runtime,
            container_name
        )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if (
            run_result["success"]
            and status["exists"]
            and status["running"]
        ):

            # Update session port/containerfile
            session["port"] = port
            session["containerfile"] = (
                edited_containerfile
            )

            return jsonify({
                "status": "success",
                "message": (
                    "Edited Containerfile successfully "
                    "built and container is running."
                ),
                "migration_id": migration_id,
                "container_runtime": runtime,
                "container_name": container_name,
                "image_name": image_name,
                "port": port,
                "container_status": status,
                "containerfile": edited_containerfile
            }), 200

        # ----------------------------------------------------
        # Container created but stopped
        # ----------------------------------------------------

        container_logs = ""

        container_inspect = ""

        if status["exists"]:

            container_logs = get_container_logs(
                target_ssh,
                runtime,
                container_name
            )

            container_inspect = get_container_inspect(
                target_ssh,
                runtime,
                container_name
            )

        return jsonify({
            "status": "manual_retry_required",
            "message": (
                "Edited Containerfile was built, "
                "but the container is not running."
            ),
            "migration_id": migration_id,
            "container_runtime": runtime,
            "container_name": container_name,
            "image_name": image_name,
            "port": port,
            "containerfile": edited_containerfile,
            "run_result": run_result,
            "container_status": status,
            "container_logs": container_logs,
            "container_inspect": container_inspect,
            "image_info": image_info
        }), 200

    except Exception as exc:

        import traceback
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500

    finally:

        if target_ssh:
            target_ssh.close()


# ============================================================
# OPTIONAL: CHECK MIGRATION STATUS
# ============================================================

@app.route(
    "/api/non-container-to-container-status/<migration_id>",
    methods=["GET"]
)
def migration_status(migration_id):

    session = get_migration_session(
        migration_id
    )

    if not session:
        return jsonify({
            "status": "error",
            "message": "Migration session not found"
        }), 404

    target_ssh = None

    try:

        target = session["target"]

        target_ssh = connect_ssh(
            host=target["ip"],
            username=target["username"],
            password=target.get("password"),
            port=target.get("port", 22)
        )

        status = get_container_status(
            target_ssh,
            session["runtime"],
            session["container_name"]
        )

        return jsonify({
            "status": "success",
            "migration_id": migration_id,
            "container_runtime": session[
                "runtime"
            ],
            "container_name": session[
                "container_name"
            ],
            "image_name": session[
                "image_name"
            ],
            "port": session[
                "port"
            ],
            "container_status": status
        })

    except Exception as exc:

        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500

    finally:

        if target_ssh:
            target_ssh.close()


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                1201
            )
        ),
        debug=False
    )