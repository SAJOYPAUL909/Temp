def get_saved_source_connection(source_connection_id):
    # Example:
    # from your_project.auth import current_user_id
    # from your_project.db import get_source_connection_for_user
    # row = get_source_connection_for_user(source_connection_id, current_user_id())
    # if not row:
    #     raise PermissionError("Source connection not found or not authorized.")
    # return {
    #     "host": row.host,
    #     "port": row.port or 22,
    #     "username": row.username,
    #     "password": decrypt_if_needed(row.encrypted_password),
    #     "private_key": decrypt_if_needed(row.encrypted_private_key),
    #     "runtime": row.runtime or "auto",
    #     "known_hosts": "/etc/atm/known_hosts",
    # }
    raise NotImplementedError(
        "Connect get_saved_source_connection() to the existing ATM source connection store "
        "and enforce per-user authorization."
    )
