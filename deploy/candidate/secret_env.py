"""Load mounted secrets, then exec upstream's entrypoint. Never print values."""

import os
import sys
from pathlib import Path
from urllib.parse import quote


def main():
    names = (
        "POSTGRES_PASSWORD",
        "LITELLM_MASTER_KEY",
        "LITELLM_SALT_KEY",
        "UI_PASSWORD",
        "CPA_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    )
    for name in names:
        path = os.environ.get(name + "_FILE")
        if path:
            try:
                value = Path(path).read_text().rstrip("\r\n")
                if not value or "\n" in value or "\x00" in value:
                    raise ValueError("invalid secret")
            except (OSError, ValueError):
                raise SystemExit(f"cannot load {name}_FILE") from None
            os.environ[name] = value
    os.environ["DATABASE_URL"] = (
        "postgresql://litellm:"
        + quote(os.environ["POSTGRES_PASSWORD"], safe="")
        + "@postgres:5432/litellm"
    )
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
