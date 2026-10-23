"""Create local Compose secrets once; never rotate existing credentials implicitly."""

import base64
import os
import secrets
import sys
from pathlib import Path

directory = Path(sys.argv[1] if len(sys.argv) > 1 else "secrets")
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
directory.chmod(0o700)
names = (
    "postgres_password",
    "keycloak_db_password",
    "keycloak_admin_password",
    "keycloak_client_secret",
    "cpa_management_key",
    "cpa_client_key",
    "cpamp_admin_key",
    "cpamp_data_key",
    "langfuse_public_key",
    "langfuse_secret_key",
)
for name in names:
    if name.startswith("langfuse_"):
        value = ""  # Supply real project credentials when configuring Langfuse.
    elif name == "cpamp_data_key":
        value = base64.b64encode(secrets.token_bytes(32)).decode() + "\n"
    else:
        value = secrets.token_urlsafe(32) + "\n"
    try:
        # File-backed Compose secrets retain host permissions. Readable by container
        # UIDs; the 0700 parent prevents other host users from traversing this path.
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        continue
    with os.fdopen(fd, "w") as output:
        os.fchmod(output.fileno(), 0o644)
        output.write(value)
print(f"Secret files ready in {directory}; existing values preserved.")
