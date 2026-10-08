from flask import Blueprint, request, jsonify
import paramiko
import os
import json
import re
import shutil
import requests
import base64
import time

from db import load_config
from migrate_non_container import (
    run_remote_command,
    create_remote_temp_dir,
    cleanup_remote_dir
)


bp = Blueprint(
    "non_container_to_container_migrate",
    __name__
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_CONTAINERIZATION_ATTEMPTS = 5
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 120
CONTAINER_START_WAIT = 8


# ============================================================
# LLM - CONTAINERFILE GENERATION / REPAIR
# ============================================================

def call_llm_for_containerfile(context, previous_attempt=None):
    """
    Generate the initial Containerfile or repair the previous
    Containerfile based on build/runtime failure evidence.
    """

    api_key = os.environ.get("api_key")

    cfg = load_config(
        os.environ.get("environment") or "local"
    )

    model_name = cfg.get("model_name", {})
    model_url = cfg.get("model_url", {})

    previous_attempt = previous_attempt or {}

    prompt = f"""
You are an expert DevOps engineer specializing in:

- Docker
- Podman
- Linux application troubleshooting
- Application containerization
- Python
- Node.js
- Java
- Frontend applications
- Backend applications
- Production container deployment
- Automated Containerfile repair

Your task is to generate a COMPLETE and RUNNABLE Containerfile for
the non-containerized application described below.

============================================================
APPLICATION INFORMATION
============================================================

PID:
{context.get("pid")}

Working Directory:
{context.get("working_directory")}

Process Information:
{context.get("process_info")}

Detected Listening Port:
{context.get("port")}

Port Command Output:
{context.get("port_info")}

Technology Stack:
{context.get("tech_stack")}

Files Present:
{json.dumps(context.get("files", []), indent=2)}

============================================================
PREVIOUS ATTEMPT INFORMATION
============================================================

Attempt Number:
{previous_attempt.get("attempt", 0)}

Previous Containerfile:
{previous_attempt.get("containerfile", "NONE")}

Build Logs:
{previous_attempt.get("build_logs", "NONE")}

Container Logs:
{previous_attempt.get("container_logs", "NONE")}

Container Inspect:
{previous_attempt.get("container_inspect", "NONE")}

Image Information:
{previous_attempt.get("image_info", "NONE")}

Failure Reason:
{previous_attempt.get("failure_reason", "NONE")}

============================================================
PRIMARY OBJECTIVE
============================================================

The Containerfile must achieve ALL of the following:

1. Build successfully.
2. Create the required image.
3. Start the application successfully.
4. Keep the container running.
5. Start the actual application process as the main
   container process.
6. Use the correct application startup command.
7. Use the correct technology/runtime.
8. Use the correct application port.
9. Make server applications listen on 0.0.0.0 whenever applicable.
10. Do not depend on files or paths from the source VM.
11. Work with both Docker and Podman.

============================================================
RETRY / FAILURE REPAIR
============================================================

If this is the FIRST attempt:

Generate the best Containerfile from the application evidence.

If this is a RETRY:

DO NOT blindly generate a new Containerfile.

First analyze:

1. Previous Containerfile
2. Build logs
3. Container logs
4. Container inspect output
5. Image information
6. Application process information
7. Port information

Determine the ROOT CAUSE of the failure.

Possible causes include:

- incorrect base image
- incompatible runtime version
- missing OS package
- missing application dependency
- incorrect dependency installation
- npm dependency failure
- Python dependency failure
- incorrect WORKDIR
- incorrect COPY path
- incorrect startup command
- incorrect CMD
- incorrect ENTRYPOINT
- incorrect executable path
- application starts and immediately exits
- application binds only to localhost
- incorrect port
- missing environment variable
- missing configuration
- permissions
- incorrect user
- Python virtual environment copied incorrectly
- Node modules copied incorrectly
- native dependency problem
- Java runtime problem
- frontend production server problem
- backend startup problem
- application-specific runtime failure

After identifying the root cause:

1. Preserve everything that is already correct.
2. Modify only what is required to fix the failure.
3. Generate a corrected Containerfile.
4. Do not make random changes.
5. Do not downgrade working dependencies unless the logs prove
   that a compatibility issue exists.

============================================================
GENERAL CONTAINERFILE RULES
============================================================

1. OUTPUT ONLY THE RAW CONTAINERFILE.

2. Do NOT output:
   - Markdown
   - explanations
   - comments outside the Containerfile
   - ```dockerfile
   - ```

3. The output must be directly usable as a Dockerfile or
   Containerfile.

4. Select a base image compatible with the detected technology.

5. Use stable, explicitly versioned base images.

6. Prefer minimal images where compatibility allows it.

7. Do NOT blindly use Alpine.

8. Use Docker layer caching correctly.

9. Copy dependency/manifest files before application source
   whenever possible.

10. Install only dependencies required to run the application.

11. Do NOT copy:

    .git
    .env
    node_modules
    venv
    .venv
    __pycache__
    logs
    temporary files

12. Do not copy an existing host virtual environment.

13. Do not copy host node_modules.

14. Set an explicit WORKDIR.

15. Use explicit COPY instructions.

16. Use an explicit CMD or ENTRYPOINT.

17. The application must run in the foreground.

18. NEVER use commands such as:

    tail -f /dev/null
    sleep infinity
    while true; do sleep ...

   merely to keep the container alive.

19. The actual application process must keep the container alive.

20. Use a non-root user whenever technically possible.

21. Do not embed passwords, API keys, tokens or other secrets.

22. Do not copy .env into the image.

23. Environment variables required by the application should be
    supplied at runtime.

24. Do not use host networking.

25. Do not use privileged mode.

26. Do not use host filesystem paths.

27. Do not invent application ports.

28. If a listening port is available from the evidence, use it.

29. If a port cannot be confidently identified, use the application
    configuration/evidence to determine it. Do not randomly select
    a port.

30. EXPOSE the actual application port when applicable.

============================================================
PYTHON APPLICATION RULES
============================================================

If the application is Python:

1. Select a compatible Python version.

2. Use requirements.txt when present.

3. If requirements.txt exists, install it.

4. Do not copy the source machine's virtual environment.

5. Use:

       python -m pip

   where appropriate.

6. Determine the correct startup command from the application.

7. If the application is Flask/FastAPI/Django/etc., determine the
   actual application module and object from the available evidence.

8. Make web applications listen on:

       0.0.0.0

9. Do not assume app.py, main.py, or another filename unless the
   evidence supports it.

============================================================
NODE.JS APPLICATION RULES
============================================================

If the application is Node.js:

1. Select a Node version compatible with package.json.

2. If package-lock.json exists, prefer:

       npm ci

3. If npm ci fails because of legacy peer dependencies, use:

       npm ci --legacy-peer-deps

4. If package-lock.json does not exist, use:

       npm install --legacy-peer-deps

5. Do not blindly use npm install when package-lock.json exists.

6. Do not copy node_modules.

7. Inspect package.json scripts to determine the correct startup
   command.

8. Do not invent npm scripts.

9. For production applications, avoid unnecessary development
   dependencies when possible.

============================================================
JAVA APPLICATION RULES
============================================================

If the application is Java:

1. Determine the Java version from the available evidence.

2. Use a compatible JDK/JRE.

3. Determine whether the application is:

   - JAR
   - WAR
   - Spring Boot
   - Tomcat
   - another Java application

4. Use the actual application artifact.

5. Use the correct startup command.

6. Do not invent JAR filenames.

============================================================
FRONTEND APPLICATION RULES
============================================================

If the application is a frontend:

1. Determine whether it is:

   - Vite
   - React
   - Next.js
   - Angular
   - Vue
   - another framework

2. Determine the correct build command.

3. Determine the correct production startup mechanism.

4. Do not assume npm run dev is suitable for production.

5. If a production server is required, make sure it binds to
   0.0.0.0.

============================================================
SECURITY RULES
============================================================

- Never embed secrets.
- Never embed passwords.
- Never embed API keys.
- Never copy .env.
- Avoid running as root.
- Do not use privileged mode.
- Do not use host networking.
- Do not depend on the host filesystem.
- Do not use arbitrary infinite loops.
- Do not weaken security merely to make the application run.

============================================================
SUCCESS CONDITION
============================================================

The objective is NOT simply to produce a valid image.

The objective is:

    Containerfile builds successfully
             AND
    Image is created
             AND
    Container is created
             AND
    Container is running
             AND
    Application process is running
             AND
    Application listens on the expected port

Return ONLY the final Containerfile.
"""

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert DevOps engineer specializing "
                    "in Docker, Podman, Linux application "
                    "troubleshooting and automated Containerfile repair."
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

    try:
        response = requests.post(
            model_url,
            json=payload,
            headers=headers,
            timeout=600
        )

        if response.status_code != 200:
            print(
                "LLM Containerfile generation failed:",
                response.status_code,
                response.text
            )

            return "# Containerfile generation failed"

        content = (
            response
            .json()["choices"][0]["message"]["content"]
            .strip()
        )

        content = re.sub(
            r"^```(?:dockerfile|Dockerfile|containerfile|Containerfile)?\s*",
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

    except Exception as e:
        print("LLM Containerfile error:", str(e))
        return f"# Containerfile generation error: {str(e)}"


# ============================================================
# CONTAINER STATUS
# ============================================================

def get_container_status(
    ssh,
    runtime,
    container_name
):
    cmd = (
        f"sudo {runtime} ps -a "
        f"--filter name=^{container_name}$ "
        f"--format '{{{{.ID}}}}|{{{{.Status}}}}'"
    )

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        cmd,
        timeout=60
    )

    if exit_code != 0:
        return {
            "exists": False,
            "running": False,
            "status": "",
            "container_id": "",
            "error": stderr
        }

    output = stdout.strip()

    if not output:
        return {
            "exists": False,
            "running": False,
            "status": "",
            "container_id": ""
        }

    parts = output.split("|", 1)

    container_id = parts[0].strip()
    status = (
        parts[1].strip()
        if len(parts) > 1
        else ""
    )

    running = status.lower().startswith("up")

    return {
        "exists": True,
        "running": running,
        "status": status,
        "container_id": container_id
    }


# ============================================================
# CONTAINER LOGS
# ============================================================

def get_container_logs(
    ssh,
    runtime,
    container_name
):
    cmd = (
        f"sudo {runtime} logs "
        f"--tail 300 "
        f"{container_name}"
    )

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        cmd,
        timeout=60
    )

    if stdout.strip():
        return stdout

    return stderr


# ============================================================
# CONTAINER INSPECT
# ============================================================

def get_container_inspect(
    ssh,
    runtime,
    container_name
):
    cmd = (
        f"sudo {runtime} inspect "
        f"{container_name}"
    )

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        cmd,
        timeout=60
    )

    if exit_code == 0:
        return stdout

    return stderr


# ============================================================
# IMAGE CHECK
# ============================================================

def check_image(
    ssh,
    runtime,
    image_name
):
    cmd = (
        f"sudo {runtime} image inspect "
        f"{image_name}"
    )

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        cmd,
        timeout=60
    )

    return {
        "exists": exit_code == 0,
        "output": (
            stdout
            if exit_code == 0
            else stderr
        )
    }


# ============================================================
# RUNTIME DETECTION
# ============================================================

def detect_container_runtime(ssh):
    exit_code, stdout, stderr = run_remote_command(
        ssh,
        "command -v docker"
    )

    if exit_code == 0 and stdout.strip():
        return "docker"

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        "command -v podman"
    )

    if exit_code == 0 and stdout.strip():
        return "podman"

    return None


# ============================================================
# PORT DETECTION
# ============================================================

def extract_port(port_output, pid):
    if not port_output:
        return None

    patterns = [
        rf":(\d+).*pid={pid}",
        rf"\.(\d+).*pid={pid}",
        rf":(\d+).*users:\(\(\".*\",pid={pid}",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            port_output,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

    matches = re.findall(
        r"(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|\*)[:.]([0-9]{2,5})",
        port_output
    )

    if matches:
        return matches[0]

    return None


# ============================================================
# SAFE REMOTE FILE WRITE
# ============================================================

def write_remote_file(
    ssh,
    remote_path,
    content
):
    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    cmd = (
        f"echo '{encoded}' | "
        f"base64 -d > '{remote_path}'"
    )

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        cmd,
        timeout=60
    )

    return exit_code, stdout, stderr


# ============================================================
# TRANSFER CONTAINERFILE
# ============================================================

def transfer_containerfile(
    ssh,
    target_path,
    content
):
    try:
        sftp = ssh.open_sftp()

        with sftp.open(
            target_path,
            "wb"
        ) as remote_file:
            remote_file.write(
                content.encode("utf-8")
            )

        sftp.close()

        return True, ""

    except Exception as e:
        return False, str(e)


# ============================================================
# BUILD + RUN + AUTOMATIC LLM REPAIR
# ============================================================

def build_and_run_with_repair(
    ssh,
    runtime,
    container_name,
    image_name,
    target_extract_dir,
    containerfile_content,
    context,
    max_attempts=MAX_CONTAINERIZATION_ATTEMPTS
):
    previous_attempt = {}

    containerfile_name = (
        "Dockerfile"
        if runtime == "docker"
        else "Containerfile"
    )

    target_containerfile_path = os.path.join(
        target_extract_dir,
        containerfile_name
    )

    for attempt in range(
        1,
        max_attempts + 1
    ):

        print("\n" + "=" * 80)
        print(
            f"CONTAINERIZATION ATTEMPT "
            f"{attempt}/{max_attempts}"
        )
        print("=" * 80)

        # ====================================================
        # WRITE/REPLACE CONTAINERFILE
        # ====================================================

        write_success, write_error = (
            transfer_containerfile(
                ssh,
                target_containerfile_path,
                containerfile_content
            )
        )

        if not write_success:

            previous_attempt = {
                "attempt": attempt,
                "containerfile": containerfile_content,
                "build_logs": "",
                "container_logs": "",
                "container_inspect": "",
                "image_info": "",
                "failure_reason": (
                    "Unable to transfer/replace "
                    "Containerfile on destination."
                )
            }

            if attempt >= max_attempts:
                return {
                    "success": False,
                    "attempts": attempt,
                    "stage": "containerfile_transfer",
                    "reason": previous_attempt,
                    "containerfile": containerfile_content,
                    "containerfile_name": containerfile_name,
                    "requires_user_edit": True,
                    "can_retry_with_edited_file": True
                }

            containerfile_content = (
                call_llm_for_containerfile(
                    context,
                    previous_attempt
                )
            )

            continue

        # ====================================================
        # REMOVE OLD CONTAINER
        # ====================================================

        existing_status = get_container_status(
            ssh,
            runtime,
            container_name
        )

        if existing_status["exists"]:

            run_remote_command(
                ssh,
                f"sudo {runtime} rm -f "
                f"{container_name}",
                timeout=60
            )

        # ====================================================
        # BUILD IMAGE
        # ====================================================

        build_cmd = (
            f"cd '{target_extract_dir}' && "
            f"sudo {runtime} build "
            f"--no-cache "
            f"-t '{image_name}' "
            f"."
        )

        build_exit, build_out, build_err = (
            run_remote_command(
                ssh,
                build_cmd,
                timeout=BUILD_TIMEOUT
            )
        )

        build_logs = (
            "===== BUILD STDOUT =====\n"
            + (build_out or "")
            + "\n\n"
            + "===== BUILD STDERR =====\n"
            + (build_err or "")
        )

        # ====================================================
        # BUILD FAILED
        # ====================================================

        if build_exit != 0:

            image_info = check_image(
                ssh,
                runtime,
                image_name
            )

            previous_attempt = {
                "attempt": attempt,
                "containerfile": containerfile_content,
                "build_logs": build_logs,
                "container_logs": "",
                "container_inspect": "",
                "image_info": image_info["output"],
                "failure_reason": (
                    "The container image build failed. "
                    "Analyze the build logs and repair "
                    "the Containerfile."
                )
            }

            if attempt >= max_attempts:
                return {
                    "success": False,
                    "attempts": attempt,
                    "stage": "build",
                    "reason": previous_attempt,
                    "container_name": container_name,
                    "image_name": image_name,
                    "container_runtime": runtime,
                    "containerfile": containerfile_content,
                    "containerfile_name": containerfile_name,
                    "requires_user_edit": True,
                    "can_retry_with_edited_file": True
                }

            containerfile_content = (
                call_llm_for_containerfile(
                    context,
                    previous_attempt
                )
            )

            continue

        # ====================================================
        # IMAGE EXISTS?
        # ====================================================

        image_info = check_image(
            ssh,
            runtime,
            image_name
        )

        if not image_info["exists"]:

            previous_attempt = {
                "attempt": attempt,
                "containerfile": containerfile_content,
                "build_logs": build_logs,
                "container_logs": "",
                "container_inspect": "",
                "image_info": image_info["output"],
                "failure_reason": (
                    "Build returned success but "
                    "the expected image does not exist."
                )
            }

            if attempt >= max_attempts:
                return {
                    "success": False,
                    "attempts": attempt,
                    "stage": "image",
                    "reason": previous_attempt,
                    "container_name": container_name,
                    "image_name": image_name,
                    "container_runtime": runtime,
                    "containerfile": containerfile_content,
                    "containerfile_name": containerfile_name,
                    "requires_user_edit": True,
                    "can_retry_with_edited_file": True
                }

            containerfile_content = (
                call_llm_for_containerfile(
                    context,
                    previous_attempt
                )
            )

            continue

        # ====================================================
        # PORT
        # ====================================================

        port = context.get("port")

        if not port:
            previous_attempt = {
                "attempt": attempt,
                "containerfile": containerfile_content,
                "build_logs": build_logs,
                "container_logs": "",
                "container_inspect": "",
                "image_info": image_info["output"],
                "failure_reason": (
                    "Application listening port could not be "
                    "determined confidently. A port must be "
                    "provided before the container can be run."
                )
            }

            if attempt >= max_attempts:
                return {
                    "success": False,
                    "attempts": attempt,
                    "stage": "port",
                    "reason": previous_attempt,
                    "container_name": container_name,
                    "image_name": image_name,
                    "container_runtime": runtime,
                    "containerfile": containerfile_content,
                    "containerfile_name": containerfile_name,
                    "requires_user_edit": True,
                    "can_retry_with_edited_file": True
                }

            containerfile_content = (
                call_llm_for_containerfile(
                    context,
                    previous_attempt
                )
            )

            continue

        # ====================================================
        # RUN CONTAINER
        # ====================================================

        run_cmd = (
            f"sudo {runtime} run -d "
            f"--name '{container_name}' "
            f"-p {port}:{port} "
            f"'{image_name}'"
        )

        run_exit, run_out, run_err = (
            run_remote_command(
                ssh,
                run_cmd,
                timeout=RUN_TIMEOUT
            )
        )

        # ====================================================
        # WAIT FOR APPLICATION
        # ====================================================

        time.sleep(
            CONTAINER_START_WAIT
        )

        # ====================================================
        # CHECK CONTAINER
        # ====================================================

        status = get_container_status(
            ssh,
            runtime,
            container_name
        )

        # ====================================================
        # SUCCESS
        # ====================================================

        if (
            run_exit == 0
            and status["exists"]
            and status["running"]
        ):
            return {
                "success": True,
                "attempts": attempt,
                "container_name": container_name,
                "image_name": image_name,
                "container_runtime": runtime,
                "port": port,
                "status": status,
                "run_command": run_cmd,
                "containerfile": containerfile_content,
                "containerfile_name": containerfile_name,
                "requires_user_edit": False,
                "can_retry_with_edited_file": False
            }

        # ====================================================
        # COLLECT FAILURE INFORMATION
        # ====================================================

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

        image_info = check_image(
            ssh,
            runtime,
            image_name
        )

        previous_attempt = {
            "attempt": attempt,
            "containerfile": containerfile_content,
            "build_logs": build_logs,
            "container_logs": container_logs,
            "container_inspect": container_inspect,
            "image_info": image_info["output"],
            "failure_reason": (
                "Container did not remain running. "
                "Analyze the run command, container logs, "
                "inspect output and image information."
            ),
            "run_stdout": run_out,
            "run_stderr": run_err,
            "container_status": status
        }

        # ====================================================
        # MAX ATTEMPTS
        # ====================================================

        if attempt >= max_attempts:

            return {
                "success": False,
                "attempts": attempt,
                "stage": "runtime",
                "container_name": container_name,
                "image_name": image_name,
                "container_runtime": runtime,
                "reason": previous_attempt,
                "containerfile": containerfile_content,
                "containerfile_name": containerfile_name,
                "requires_user_edit": True,
                "can_retry_with_edited_file": True
            }

        # ====================================================
        # LLM REPAIR
        # ====================================================

        containerfile_content = (
            call_llm_for_containerfile(
                context,
                previous_attempt
            )
        )

    return {
        "success": False,
        "attempts": max_attempts,
        "stage": "unknown",
        "containerfile": containerfile_content,
        "containerfile_name": containerfile_name,
        "requires_user_edit": True,
        "can_retry_with_edited_file": True
    }


# ============================================================
# RUN USER-EDITED CONTAINERFILE
# ============================================================

def run_user_containerfile(
    ssh,
    runtime,
    container_name,
    image_name,
    target_extract_dir,
    containerfile_content,
    port
):
    """
    Run a Containerfile/Dockerfile manually edited by the user.

    IMPORTANT:
    This function DOES NOT transfer the application again.

    The application was already transferred during the original
    migration. Only the edited Containerfile is replaced and
    tested.
    """

    if not containerfile_content:
        return {
            "success": False,
            "stage": "validation",
            "reason": "Containerfile content is required"
        }

    if not port:
        return {
            "success": False,
            "stage": "validation",
            "reason": (
                "Application port is required to run "
                "the edited Containerfile."
            )
        }

    containerfile_name = (
        "Dockerfile"
        if runtime == "docker"
        else "Containerfile"
    )

    target_containerfile_path = os.path.join(
        target_extract_dir,
        containerfile_name
    )

    # ========================================================
    # VERIFY APPLICATION DIRECTORY
    # ========================================================

    exit_code, stdout, stderr = run_remote_command(
        ssh,
        f"test -d '{target_extract_dir}'"
    )

    if exit_code != 0:
        return {
            "success": False,
            "stage": "application_directory",
            "reason": (
                "Transferred application directory does not "
                "exist on destination."
            ),
            "containerfile": containerfile_content,
            "containerfile_name": containerfile_name
        }

    # ========================================================
    # WRITE EDITED CONTAINERFILE
    # ========================================================

    transfer_success, transfer_error = (
        transfer_containerfile(
            ssh,
            target_containerfile_path,
            containerfile_content
        )
    )

    if not transfer_success:
        return {
            "success": False,
            "stage": "containerfile_transfer",
            "reason": transfer_error,
            "containerfile": containerfile_content,
            "containerfile_name": containerfile_name
        }

    # ========================================================
    # REMOVE OLD CONTAINER
    # ========================================================

    existing_status = get_container_status(
        ssh,
        runtime,
        container_name
    )

    if existing_status["exists"]:
        run_remote_command(
            ssh,
            f"sudo {runtime} rm -f '{container_name}'",
            timeout=60
        )

    # ========================================================
    # REMOVE OLD IMAGE
    # ========================================================

    run_remote_command(
        ssh,
        f"sudo {runtime} image rm -f '{image_name}'",
        timeout=120
    )

    # ========================================================
    # BUILD
    # ========================================================

    build_cmd = (
        f"cd '{target_extract_dir}' && "
        f"sudo {runtime} build "
        f"--no-cache "
        f"-t '{image_name}' "
        f"-f '{containerfile_name}' "
        f"."
    )

    build_exit, build_out, build_err = (
        run_remote_command(
            ssh,
            build_cmd,
            timeout=BUILD_TIMEOUT
        )
    )

    build_logs = (
        "===== BUILD STDOUT =====\n"
        + (build_out or "")
        + "\n\n"
        + "===== BUILD STDERR =====\n"
        + (build_err or "")
    )

    if build_exit != 0:

        return {
            "success": False,
            "stage": "build",
            "reason": "Edited Containerfile build failed",
            "build_logs": build_logs,
            "container_logs": "",
            "container_inspect": "",
            "containerfile": containerfile_content,
            "containerfile_name": containerfile_name,
            "requires_user_edit": True,
            "can_retry_with_edited_file": True
        }

    # ========================================================
    # CHECK IMAGE
    # ========================================================

    image_info = check_image(
        ssh,
        runtime,
        image_name
    )

    if not image_info["exists"]:

        return {
            "success": False,
            "stage": "image",
            "reason": (
                "Build completed but the expected image "
                "does not exist."
            ),
            "build_logs": build_logs,
            "image_info": image_info["output"],
            "containerfile": containerfile_content,
            "containerfile_name": containerfile_name,
            "requires_user_edit": True,
            "can_retry_with_edited_file": True
        }

    # ========================================================
    # RUN
    # ========================================================

    run_cmd = (
        f"sudo {runtime} run -d "
        f"--name '{container_name}' "
        f"-p {port}:{port} "
        f"'{image_name}'"
    )

    run_exit, run_out, run_err = (
        run_remote_command(
            ssh,
            run_cmd,
            timeout=RUN_TIMEOUT
        )
    )

    time.sleep(
        CONTAINER_START_WAIT
    )

    status = get_container_status(
        ssh,
        runtime,
        container_name
    )

    # ========================================================
    # SUCCESS
    # ========================================================

    if (
        run_exit == 0
        and status["exists"]
        and status["running"]
    ):
        return {
            "success": True,
            "attempts": 1,
            "container_name": container_name,
            "image_name": image_name,
            "container_runtime": runtime,
            "port": port,
            "status": status,
            "run_command": run_cmd,
            "containerfile": containerfile_content,
            "containerfile_name": containerfile_name,
            "requires_user_edit": False,
            "can_retry_with_edited_file": False
        }

    # ========================================================
    # FAILURE
    # ========================================================

    container_logs = ""

    if status["exists"]:
        container_logs = get_container_logs(
            ssh,
            runtime,
            container_name
        )

    container_inspect = ""

    if status["exists"]:
        container_inspect = get_container_inspect(
            ssh,
            runtime,
            container_name
        )

    return {
        "success": False,
        "attempts": 1,
        "stage": "runtime",
        "container_name": container_name,
        "image_name": image_name,
        "container_runtime": runtime,
        "port": port,
        "reason": (
            "Edited Containerfile built successfully, "
            "but the container is not running."
        ),
        "build_logs": build_logs,
        "container_logs": container_logs,
        "container_inspect": container_inspect,
        "run_stdout": run_out,
        "run_stderr": run_err,
        "status": status,
        "containerfile": containerfile_content,
        "containerfile_name": containerfile_name,
        "requires_user_edit": True,
        "can_retry_with_edited_file": True
    }


# ============================================================
# RUN EDITED CONTAINERFILE API
# ============================================================

@bp.route(
    "/api/non-container-to-container-run-edited",
    methods=["POST"]
)
def non_container_to_container_run_edited():

    ssh = None

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "error": "Request body is required",
                "status": 400
            }), 400

        pid = data.get("pid")
        port = data.get("port")
        containerfile = data.get("containerfile")
        target = data.get("target") or {}

        if not pid:
            return jsonify({
                "error": "pid is required",
                "status": 400
            }), 400

        if not containerfile:
            return jsonify({
                "error": "containerfile is required",
                "status": 400
            }), 400

        target_host = target.get("ip")
        target_user = target.get("TargetUsername")
        target_password = target.get("TargetPassword")

        if not target_host:
            return jsonify({
                "error": "Target IP is required",
                "status": 400
            }), 400

        if not target_user:
            return jsonify({
                "error": "Target username is required",
                "status": 400
            }), 400

        # ====================================================
        # CONNECT TARGET
        # ====================================================

        ssh = paramiko.SSHClient()

        ssh.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        ssh.connect(
            target_host,
            username=target_user,
            password=target_password,
            timeout=30
        )

        # ====================================================
        # DETECT RUNTIME
        # ====================================================

        runtime = detect_container_runtime(
            ssh
        )

        if not runtime:
            return jsonify({
                "error": (
                    "Neither Docker nor Podman is installed "
                    "or available on the destination."
                ),
                "status": 500
            }), 500

        # ====================================================
        # TARGET DIRECTORY
        # ====================================================

        target_extract_dir = (
            f"/home/{target_user}/{pid}_app"
        )

        container_name = (
            f"app-{pid}"
        )

        image_name = (
            f"app-{pid}"
        )

        # ====================================================
        # RUN EDITED FILE
        # ====================================================

        result = run_user_containerfile(
            ssh=ssh,
            runtime=runtime,
            container_name=container_name,
            image_name=image_name,
            target_extract_dir=target_extract_dir,
            containerfile_content=containerfile,
            port=port
        )

        if result.get("success"):

            return jsonify({
                "message": (
                    f"Application {pid} successfully "
                    f"started using the edited "
                    f"{result.get('containerfile_name')}"
                ),
                "container_name": result.get(
                    "container_name"
                ),
                "image_name": result.get(
                    "image_name"
                ),
                "container_runtime": result.get(
                    "container_runtime"
                ),
                "port": result.get("port"),
                "run_command": result.get(
                    "run_command"
                ),
                "attempts": result.get(
                    "attempts",
                    1
                ),
                "containerfile": result.get(
                    "containerfile"
                ),
                "containerfile_name": result.get(
                    "containerfile_name"
                ),
                "requires_user_edit": False,
                "can_retry_with_edited_file": False,
                "status": "running",
                "status_code": 200
            }), 200

        return jsonify({
            "message": (
                "Edited Containerfile failed. "
                "You can edit it and run it again."
            ),
            "container_name": result.get(
                "container_name",
                container_name
            ),
            "image_name": result.get(
                "image_name",
                image_name
            ),
            "container_runtime": result.get(
                "container_runtime",
                runtime
            ),
            "port": result.get("port", port),
            "attempts": result.get(
                "attempts",
                1
            ),
            "stage": result.get("stage"),
            "failure_details": result.get(
                "reason"
            ),
            "build_logs": result.get(
                "build_logs",
                ""
            ),
            "container_logs": result.get(
                "container_logs",
                ""
            ),
            "container_inspect": result.get(
                "container_inspect",
                ""
            ),
            "run_stdout": result.get(
                "run_stdout",
                ""
            ),
            "run_stderr": result.get(
                "run_stderr",
                ""
            ),
            "container_status": result.get(
                "status"
            ),
            "containerfile": result.get(
                "containerfile",
                containerfile
            ),
            "containerfile_name": result.get(
                "containerfile_name",
                (
                    "Dockerfile"
                    if runtime == "docker"
                    else "Containerfile"
                )
            ),
            "requires_user_edit": True,
            "can_retry_with_edited_file": True,
            "status": 500
        }), 500

    except Exception as e:

        print(
            "\nEdited Containerfile execution error:"
        )

        print(
            str(e)
        )

        return jsonify({
            "error": str(e),
            "status": 500
        }), 500

    finally:

        try:
            if ssh:
                ssh.close()
        except Exception:
            pass


# ============================================================
# MAIN API
# ============================================================

@bp.route(
    "/api/non-container-to-container-migrate",
    methods=["POST"]
)
def non_container_to_container_migrate():

    ssh1 = None
    ssh2 = None
    sftp1 = None
    sftp2 = None

    source_temp_dir = None
    target_extract_dir = None
    target_tar_path = None

    try:

        # ====================================================
        # REQUEST
        # ====================================================

        data = request.get_json()

        if not data:
            return jsonify({
                "error": "Request body is required",
                "status": 400
            }), 400

        pid = data.get("pid")
        tech_stack = data.get("tech_stack")
        source = data.get("source") or {}
        target = data.get("target") or {}

        if not pid:
            return jsonify({
                "error": "pid is required",
                "status": 400
            }), 400

        # ====================================================
        # SOURCE DETAILS
        # ====================================================

        source_host = source.get("host")
        source_user = source.get("user")
        source_password = source.get("password")
        source_sudo = source.get("sudo_password")

        # ====================================================
        # TARGET DETAILS
        # ====================================================

        target_host = target.get("ip")
        target_user = target.get("TargetUsername")
        target_password = target.get("TargetPassword")
        target_sudo = target.get("TargetSudoPassword")

        if not source_host:
            raise Exception(
                "Source host is required"
            )

        if not source_user:
            raise Exception(
                "Source username is required"
            )

        if not target_host:
            raise Exception(
                "Target IP is required"
            )

        if not target_user:
            raise Exception(
                "Target username is required"
            )

        # ====================================================
        # CONNECT SOURCE
        # ====================================================

        print(
            "\nConnecting to source:"
        )

        print(source_host)

        ssh1 = paramiko.SSHClient()

        ssh1.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        ssh1.connect(
            source_host,
            username=source_user,
            password=source_password,
            timeout=30
        )

        # ====================================================
        # GET PROCESS WORKING DIRECTORY
        # ====================================================

        exit_code, pid_path_out, err = (
            run_remote_command(
                ssh1,
                f"pwdx {pid}"
            )
        )

        if exit_code != 0:
            raise Exception(
                f"Could not get path for PID {pid}: {err}"
            )

        original_path = (
            pid_path_out
            .split(":")[-1]
            .strip()
        )

        if not original_path:
            raise Exception(
                f"Could not determine working directory "
                f"for PID {pid}"
            )

        print(
            "\nApplication working directory:"
        )

        print(original_path)

        # ====================================================
        # PROCESS INFORMATION
        # ====================================================

        exit_code, ps_out, err = (
            run_remote_command(
                ssh1,
                f"ps -fp {pid}"
            )
        )

        if exit_code != 0:
            print(
                "WARNING: ps command failed:",
                err
            )

        # ====================================================
        # APPLICATION FILES
        # ====================================================

        exit_code, ls_out, err = (
            run_remote_command(
                ssh1,
                f"ls -la '{original_path}'"
            )
        )

        if exit_code != 0:
            raise Exception(
                f"Unable to list application files: {err}"
            )

        files = ls_out.splitlines()

        # ====================================================
        # LISTENING PORT
        # ====================================================

        exit_code, port_out, err = (
            run_remote_command(
                ssh1,
                f"sudo ss -tunlp | grep 'pid={pid}'"
            )
        )

        if exit_code != 0:
            print(
                "WARNING: Could not determine "
                "application port:"
            )

            print(err)

        print(
            "\nPort information:"
        )

        print(port_out)

        detected_port = extract_port(
            port_out,
            pid
        )

        print(
            "\nDetected application port:"
        )

        print(detected_port)

        # ====================================================
        # APPLICATION CONTEXT
        # ====================================================

        context = {
            "pid": pid,
            "working_directory": original_path,
            "process_info": ps_out,
            "files": files,
            "tech_stack": tech_stack,
            "port_info": port_out,
            "port": detected_port
        }

        # ====================================================
        # INITIAL LLM CONTAINERFILE
        # ====================================================

        print(
            "\n"
            + "=" * 80
        )

        print(
            "GENERATING INITIAL CONTAINERFILE"
        )

        print(
            "=" * 80
        )

        dockerfile_content = (
            call_llm_for_containerfile(
                context
            )
        )

        if (
            not dockerfile_content
            or dockerfile_content.startswith(
                "# Containerfile generation"
            )
        ):
            raise Exception(
                "LLM failed to generate Containerfile"
            )

        print(
            "\nGenerated Containerfile:"
        )

        print(
            dockerfile_content
        )

        # ====================================================
        # SOURCE TEMP DIRECTORY
        # ====================================================

        source_temp_dir = create_remote_temp_dir(
            ssh1,
            f"/home/{source_user}"
        )

        dockerfile_path = os.path.join(
            source_temp_dir,
            "Dockerfile"
        )

        tar_path = os.path.join(
            source_temp_dir,
            f"{pid}.tar"
        )

        # ====================================================
        # WRITE INITIAL CONTAINERFILE TO SOURCE
        # ====================================================

        exit_code, out, err = write_remote_file(
            ssh1,
            dockerfile_path,
            dockerfile_content
        )

        if exit_code != 0:
            raise Exception(
                f"Failed to write Containerfile "
                f"on source: {err}"
            )

        # ====================================================
        # CREATE APPLICATION TAR
        # ====================================================

        print(
            "\nCreating application archive..."
        )

        tar_cmd = (
            f"cd '{original_path}' && "
            f"tar -cf '{tar_path}' "
            f"--exclude=venv "
            f"--exclude=.venv "
            f"--exclude=node_modules "
            f"--exclude=__pycache__ "
            f"--exclude=.git "
            f"--exclude=.env "
            f"--exclude='*.log' "
            f"-C . ."
        )

        exit_code, tar_out, tar_err = (
            run_remote_command(
                ssh1,
                tar_cmd,
                timeout=600
            )
        )

        print(
            "Tar output:"
        )

        print(tar_out)

        if exit_code != 0:
            raise Exception(
                f"Tar creation failed: {tar_err}"
            )

        # ====================================================
        # CONNECT TARGET
        # ====================================================

        print(
            "\nConnecting to target:"
        )

        print(target_host)

        ssh2 = paramiko.SSHClient()

        ssh2.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        ssh2.connect(
            target_host,
            username=target_user,
            password=target_password,
            timeout=30
        )

        # ====================================================
        # DETECT DOCKER / PODMAN
        # ====================================================

        container_runtime = (
            detect_container_runtime(ssh2)
        )

        if not container_runtime:
            raise Exception(
                "Neither Docker nor Podman is installed "
                "or available on the destination."
            )

        print(
            "\nContainer runtime:"
        )

        print(container_runtime)

        # ====================================================
        # TARGET PATHS
        # ====================================================

        target_extract_dir = (
            f"/home/{target_user}/{pid}_app"
        )

        target_tar_path = (
            f"/home/{target_user}/{pid}.tar"
        )

        containerfile_name = (
            "Dockerfile"
            if container_runtime == "docker"
            else "Containerfile"
        )

        target_containerfile_path = os.path.join(
            target_extract_dir,
            containerfile_name
        )

        container_name = (
            f"app-{pid}"
        )

        image_name = (
            f"app-{pid}"
        )

        # ====================================================
        # CREATE TARGET DIRECTORY
        # ====================================================

        exit_code, out, err = (
            run_remote_command(
                ssh2,
                f"mkdir -p '{target_extract_dir}'"
            )
        )

        if exit_code != 0:
            raise Exception(
                f"Unable to create target directory: {err}"
            )

        # ====================================================
        # SFTP TRANSFER
        # ====================================================

        print(
            "\nTransferring application to destination..."
        )

        sftp1 = ssh1.open_sftp()
        sftp2 = ssh2.open_sftp()

        # ----------------------------------------------------
        # Transfer Containerfile
        # ----------------------------------------------------

        with sftp2.open(
            target_containerfile_path,
            "wb"
        ) as destination_file:

            destination_file.write(
                dockerfile_content.encode("utf-8")
            )

        # ----------------------------------------------------
        # Transfer tar
        # ----------------------------------------------------

        with sftp1.open(
            tar_path,
            "rb"
        ) as source_file:

            with sftp2.open(
                target_tar_path,
                "wb"
            ) as destination_file:

                shutil.copyfileobj(
                    source_file,
                    destination_file,
                    length=16 * 1024 * 1024
                )

        sftp1.close()
        sftp1 = None

        sftp2.close()
        sftp2 = None

        # ====================================================
        # EXTRACT APPLICATION
        # ====================================================

        print(
            "\nExtracting application..."
        )

        extract_cmd = (
            f"tar -xf '{target_tar_path}' "
            f"-C '{target_extract_dir}'"
        )

        exit_code, out, err = (
            run_remote_command(
                ssh2,
                extract_cmd,
                timeout=600
            )
        )

        if exit_code != 0:
            raise Exception(
                f"Application extraction failed: {err}"
            )

        # ====================================================
        # REPLACE CONTAINERFILE AFTER EXTRACTION
        # ====================================================

        transfer_success, transfer_error = (
            transfer_containerfile(
                ssh2,
                target_containerfile_path,
                dockerfile_content
            )
        )

        if not transfer_success:
            raise Exception(
                "Unable to place Containerfile after "
                f"application extraction: {transfer_error}"
            )

        # ====================================================
        # BUILD + RUN + REPAIR
        # ====================================================

        result = build_and_run_with_repair(
            ssh=ssh2,
            runtime=container_runtime,
            container_name=container_name,
            image_name=image_name,
            target_extract_dir=target_extract_dir,
            containerfile_content=dockerfile_content,
            context=context,
            max_attempts=MAX_CONTAINERIZATION_ATTEMPTS
        )

        # ====================================================
        # SUCCESS
        # ====================================================

        if result.get("success"):

            print(
                "\nMigration completed successfully."
            )

            # Remove source temporary directory.
            if source_temp_dir:
                try:
                    cleanup_remote_dir(
                        ssh1,
                        source_temp_dir
                    )
                except Exception as cleanup_error:
                    print(
                        "Source cleanup warning:",
                        cleanup_error
                    )

            # Remove target tar only.
            try:
                cleanup_remote_dir(
                    ssh2,
                    target_tar_path
                )
            except Exception as cleanup_error:
                print(
                    "Target tar cleanup warning:",
                    cleanup_error
                )

            return jsonify({
                "message": (
                    f"Non-container application {pid} "
                    f"migrated successfully to container"
                ),
                "container_name": container_name,
                "image_name": image_name,
                "container_runtime": container_runtime,
                "port": result.get("port"),
                "run_command": result.get(
                    "run_command"
                ),
                "attempts": result.get(
                    "attempts"
                ),
                "containerfile": result.get(
                    "containerfile"
                ),
                "containerfile_name": result.get(
                    "containerfile_name",
                    containerfile_name
                ),
                "requires_user_edit": False,
                "can_retry_with_edited_file": False,
                "application_transferred": True,
                "status": "running",
                "status_code": 200
            }), 200

        # ====================================================
        # FAILURE AFTER 5 ATTEMPTS
        # ====================================================

        return jsonify({
            "message": (
                f"Unable to successfully run "
                f"application {pid} in destination "
                f"after {result.get('attempts', MAX_CONTAINERIZATION_ATTEMPTS)} "
                f"attempts."
            ),
            "container_name": result.get(
                "container_name",
                container_name
            ),
            "image_name": result.get(
                "image_name",
                image_name
            ),
            "container_runtime": result.get(
                "container_runtime",
                container_runtime
            ),
            "port": result.get(
                "port",
                detected_port
            ),
            "attempts": result.get(
                "attempts",
                MAX_CONTAINERIZATION_ATTEMPTS
            ),
            "stage": result.get(
                "stage"
            ),
            "failure_details": result.get(
                "reason"
            ),
            "containerfile": result.get(
                "containerfile",
                dockerfile_content
            ),
            "containerfile_name": result.get(
                "containerfile_name",
                containerfile_name
            ),
            "requires_user_edit": True,
            "can_retry_with_edited_file": True,
            "application_transferred": True,
            "status": 500
        }), 500

    except Exception as e:

        print(
            "\nMigration error:"
        )

        print(
            str(e)
        )

        return jsonify({
            "error": str(e),
            "status": 500
        }), 500

    finally:

        # ====================================================
        # SFTP CLEANUP
        # ====================================================

        try:
            if sftp1:
                sftp1.close()
        except Exception:
            pass

        try:
            if sftp2:
                sftp2.close()
        except Exception:
            pass

        # ====================================================
        # SSH CLEANUP
        # ====================================================

        try:
            if ssh1:
                ssh1.close()
        except Exception:
            pass

        try:
            if ssh2:
                ssh2.close()
        except Exception:
            pass
