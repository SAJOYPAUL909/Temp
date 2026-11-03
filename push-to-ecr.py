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
        # 5. Commit container into a new image
        # ---------------------------------------------

        remote_command(
            ssh,
            (
                f"{runtime} commit "
                f"{shlex.quote(container_id)} "
                f"{shlex.quote(image_uri)}"
            ),
            timeout=300  # Commits can take a bit longer depending on container size
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

            "message": "Container committed and image pushed successfully to ECR",

            "source": {
                "container_id": container_id,
                "container_name": container_name,
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
