
import re
import time
import socket
import paramiko

from flask import Blueprint, request, jsonify

bp = Blueprint("migration_smoke_test", __name__)

SSH_TIMEOUT = 12
COMMAND_TIMEOUT = 10

VALID_MIGRATION_TYPES = {
    "non_container",
    "container",
    "non_container_to_container",
}

# Restrict values interpolated into remote shell commands.
SAFE_CONTAINER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


def _check(name, status, message, details=None, duration_ms=0):
    """Create a consistent result object for the frontend."""
    return {
        "name": name,
        "status": status,  # passed | failed | skipped | warning
        "message": message,
        "details": details or "",
        "duration_ms": duration_ms,
    }


def _run_command(ssh, command, timeout=COMMAND_TIMEOUT):
    """Execute a fixed or validated command without requesting sudo."""
    stdin, stdout, stderr = ssh.exec_command(
        command,
        timeout=timeout,
        get_pty=False,
    )
    exit_code = stdout.channel.recv_exit_status()

    return {
        "exit_code": exit_code,
        "stdout": stdout.read().decode("utf-8", errors="replace").strip(),
        "stderr": stderr.read().decode("utf-8", errors="replace").strip(),
    }


def _target_value(target, *keys):
    """Read target values while accepting the field names used by the UI."""
    for key in keys:
        value = target.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _skipped(name, reason):
    return _check(name, "skipped", reason)


def _smoke_test(ssh, migration_type, app):
    results = []
    started = time.time()

    # ---------------------------------------------------------
    # 1. Verify SSH command execution
    # ---------------------------------------------------------
    try:
        result = _run_command(ssh, "printf 'ssh-ok'")
        if result["exit_code"] == 0 and result["stdout"] == "ssh-ok":
            results.append(_check(
                "Destination command execution",
                "passed",
                "SSH connected and remote commands executed.",
                duration_ms=int((time.time() - started) * 1000),
            ))
        else:
            results.append(_check(
                "Destination command execution",
                "failed",
                "The SSH session opened, but the test command failed.",
                result["stderr"] or result["stdout"],
            ))
    except Exception as exc:
        results.append(_check(
            "Destination command execution",
            "failed",
            "Unable to execute a command on the destination.",
            str(exc),
        ))
        return results

    pid = str(app.get("pid", "")).strip()
    port = str(app.get("port", "")).strip()
    container_name = str(
        app.get("container_name")
        or app.get("name")
        or ""
    ).strip()

    # ---------------------------------------------------------
    # 2. Non-container process check
    # ---------------------------------------------------------
    if migration_type == "non_container":
        if pid.isdigit() and int(pid) > 0:
            t0 = time.time()
            try:
                result = _run_command(
                    ssh,
                    f"ps -p {int(pid)} -o pid=,stat=,comm=",
                )
                if result["exit_code"] == 0 and result["stdout"]:
                    results.append(_check(
                        "Application process",
                        "passed",
                        f"Process {pid} exists on the destination.",
                        result["stdout"],
                        int((time.time() - t0) * 1000),
                    ))
                else:
                    results.append(_check(
                        "Application process",
                        "failed",
                        f"Process {pid} was not found on the destination.",
                        result["stderr"] or "No process information returned.",
                        int((time.time() - t0) * 1000),
                    ))
            except Exception as exc:
                results.append(_check(
                    "Application process",
                    "warning",
                    "Could not verify the process.",
                    str(exc),
                ))
        else:
            results.append(_skipped(
                "Application process",
                "Provide a destination process PID to verify process status.",
            ))

    # ---------------------------------------------------------
    # 3. Container runtime / container status
    # ---------------------------------------------------------
    if migration_type in {"container", "non_container_to_container"}:
        t0 = time.time()
        try:
            runtime_result = _run_command(
                ssh,
                "command -v podman >/dev/null 2>&1 && "
                "printf podman; "
                "command -v docker >/dev/null 2>&1 && "
                "printf ' docker'",
            )
            runtimes = runtime_result["stdout"].split()

            if runtimes:
                results.append(_check(
                    "Container runtime",
                    "passed",
                    "A container runtime is installed.",
                    ", ".join(runtimes),
                    int((time.time() - t0) * 1000),
                ))
            else:
                results.append(_check(
                    "Container runtime",
                    "failed",
                    "Neither Podman nor Docker was found for this SSH user.",
                    runtime_result["stderr"] or
                    "Check runtime installation and user permissions.",
                    int((time.time() - t0) * 1000),
                ))

            if container_name and SAFE_CONTAINER_NAME.fullmatch(container_name):
                found = False
                inspect_errors = []

                for runtime in ("podman", "docker"):
                    if runtime not in runtimes:
                        continue

                    inspect = _run_command(
                        ssh,
                        f"{runtime} inspect --format "
                        f"'{{{{.State.Running}}}}' {container_name}",
                    )

                    if inspect["exit_code"] == 0:
                        found = True
                        is_running = inspect["stdout"].lower() == "true"

                        results.append(_check(
                            "Container status",
                            "passed" if is_running else "failed",
                            (
                                f"Container '{container_name}' is running."
                                if is_running
                                else f"Container '{container_name}' exists but is not running."
                            ),
                            inspect["stdout"] or inspect["stderr"],
                            int((time.time() - t0) * 1000),
                        ))

                        if not is_running:
                            logs = _run_command(
                                ssh,
                                f"{runtime} logs --tail 30 {container_name}",
                                timeout=15,
                            )
                            if logs["stdout"] or logs["stderr"]:
                                results.append(_check(
                                    "Container logs",
                                    "warning",
                                    "Recent logs from the container.",
                                    (logs["stdout"] or logs["stderr"])[-6000:],
                                ))
                        break

                    inspect_errors.append(
                        f"{runtime}: {inspect['stderr'] or 'not found'}"
                    )

                if not found:
                    results.append(_check(
                        "Container status",
                        "failed",
                        f"Container '{container_name}' was not found.",
                        "\n".join(inspect_errors) or
                        "Container name was not found in the available runtimes.",
                    ))
            elif container_name:
                results.append(_check(
                    "Container status",
                    "warning",
                    "Container name contains unsupported characters.",
                    "Use letters, numbers, dots, underscores or hyphens.",
                ))
            else:
                results.append(_skipped(
                    "Container status",
                    "Provide application.container_name or application.name.",
                ))

        except Exception as exc:
            results.append(_check(
                "Container runtime / status",
                "failed",
                "Could not verify the container runtime or container.",
                str(exc),
            ))

    # ---------------------------------------------------------
    # 4. Listening port check
    # ---------------------------------------------------------
    if port.isdigit() and 1 <= int(port) <= 65535:
        port_number = int(port)
        t0 = time.time()
        try:
            result = _run_command(
                ssh,
                "ss -ltnH 2>/dev/null | "
                f"grep -E '[:.]{port_number}[[:space:]]'",
            )
            if result["exit_code"] == 0 and result["stdout"]:
                results.append(_check(
                    "Listening port",
                    "passed",
                    f"Port {port_number} is listening on the destination.",
                    result["stdout"],
                    int((time.time() - t0) * 1000),
                ))
            else:
                results.append(_check(
                    "Listening port",
                    "failed",
                    f"No listening TCP socket was detected for port {port_number}.",
                    result["stderr"] or "No matching listening socket.",
                    int((time.time() - t0) * 1000),
                ))
        except Exception as exc:
            results.append(_check(
                "Listening port",
                "warning",
                "Could not verify the listening port.",
                str(exc),
            ))

        # Optional HTTP check. This only checks HTTP on localhost.
        if app.get("check_http", True):
            t0 = time.time()
            try:
                http_result = _run_command(
                    ssh,
                    "curl --silent --show-error --output /dev/null "
                    "--write-out '%{http_code}' --max-time 5 "
                    f"http://127.0.0.1:{port_number}/",
                    timeout=8,
                )
                code = http_result["stdout"].strip()

                # Any HTTP response indicates the HTTP server responded.
                if code.isdigit() and int(code) > 0:
                    code_num = int(code)
                    status = "passed" if code_num < 500 else "warning"
                    results.append(_check(
                        "HTTP health check",
                        status,
                        f"HTTP endpoint responded with status {code_num}.",
                        "This checks the root path (/); it does not validate application-specific business behavior.",
                        int((time.time() - t0) * 1000),
                    ))
                else:
                    results.append(_check(
                        "HTTP health check",
                        "failed",
                        "No HTTP response was received from localhost.",
                        http_result["stderr"] or
                        "Verify that this application serves HTTP on the supplied port.",
                        int((time.time() - t0) * 1000),
                    ))
            except Exception as exc:
                results.append(_check(
                    "HTTP health check",
                    "warning",
                    "Could not complete the HTTP check.",
                    str(exc),
                ))
    else:
        results.append(_skipped(
            "Listening port",
            "Provide application.port (1–65535) to check the port.",
        ))
        results.append(_skipped(
            "HTTP health check",
            "An application port is required for the HTTP check.",
        ))

    return results


@bp.route("/api/migration-smoke-test", methods=["POST"])
def migration_smoke_test():
    """
    Test a migrated application on its destination VM.

    Expected JSON:
    {
      "migration_type": "non_container | container | non_container_to_container",
      "target": {
        "ip": "10.0.0.10",
        "TargetUsername": "user",
        "TargetPassword": "password"
      },
      "application": {
        "pid": 1234,
        "container_name": "my-app",
        "port": 8080,
        "check_http": true
      }
    }
    """
    payload = request.get_json(silent=True) or {}
    migration_type = str(payload.get("migration_type", "")).strip().lower()
    target = payload.get("target") or {}
    app = payload.get("application") or {}

    if migration_type not in VALID_MIGRATION_TYPES:
        return jsonify({
            "success": False,
            "error": "Invalid migration_type.",
            "allowed_values": sorted(VALID_MIGRATION_TYPES),
        }), 400

    if not isinstance(target, dict) or not isinstance(app, dict):
        return jsonify({
            "success": False,
            "error": "target and application must be JSON objects.",
        }), 400

    host = _target_value(target, "ip", "host", "TargetIP", "Host")
    username = _target_value(
        target, "TargetUsername", "username", "user"
    )
    password = _target_value(
        target, "TargetPassword", "password"
    )
    port_value = _target_value(target, "port", "ssh_port") or "22"

    if not host or not username or password is None:
        return jsonify({
            "success": False,
            "error": (
                "Destination SSH details are required: target.ip, "
                "target.TargetUsername and target.TargetPassword."
            ),
        }), 400

    try:
        ssh_port = int(port_value)
        if not 1 <= ssh_port <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "SSH port must be between 1 and 65535.",
        }), 400

    # Validate PID and app port before any remote command is constructed.
    if app.get("pid") not in (None, ""):
        if not str(app["pid"]).isdigit() or int(app["pid"]) <= 0:
            return jsonify({
                "success": False,
                "error": "application.pid must be a positive integer.",
            }), 400

    if app.get("port") not in (None, ""):
        if (
            not str(app["port"]).isdigit()
            or not 1 <= int(app["port"]) <= 65535
        ):
            return jsonify({
                "success": False,
                "error": "application.port must be between 1 and 65535.",
            }), 400

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    start_time = time.time()

    try:
        ssh.connect(
            hostname=host,
            port=ssh_port,
            username=username,
            password=password,
            timeout=SSH_TIMEOUT,
            banner_timeout=SSH_TIMEOUT,
            auth_timeout=SSH_TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )

        results = _smoke_test(ssh, migration_type, app)

    except (paramiko.SSHException, socket.error, TimeoutError) as exc:
        results = [
            _check(
                "SSH connection",
                "failed",
                "Unable to connect to the destination VM.",
                str(exc),
            )
        ]
    except Exception as exc:
        results = [
            _check(
                "Smoke test execution",
                "failed",
                "An unexpected error occurred during the smoke test.",
                str(exc),
            )
        ]
    finally:
        try:
            ssh.close()
        except Exception:
            pass

    failed = sum(r["status"] == "failed" for r in results)
    passed = sum(r["status"] == "passed" for r in results)
    skipped = sum(r["status"] == "skipped" for r in results)
    warnings = sum(r["status"] == "warning" for r in results)

    overall_status = (
        "failed" if failed
        else "warning" if skipped or warnings
        else "passed"
    )

    return jsonify({
        "success": failed == 0,
        "status": overall_status,
        "migration_type": migration_type,
        "destination": host,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "warnings": warnings,
        },
        "duration_ms": int((time.time() - start_time) * 1000),
        "tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
    }), 200
