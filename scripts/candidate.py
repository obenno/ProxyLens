"""Small isolated-POC setup helper. All account operations use native HTTP APIs."""

import argparse
import base64
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MODEL = "cpa-gpt-5.6-luna"
ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    with path.open("x") as stream:
        stream.write(value)


def initialize(args):
    private = args.private_dir.resolve()
    if private.is_relative_to(ROOT):
        raise SystemExit("private-dir must be outside the repository")
    if any(c in str(private) + args.cpa_base + args.cpa_network for c in "\r\n$'\""):
        raise SystemExit("unsupported Compose environment characters")
    key = args.cpa_key_file.read_text()
    if not key.strip():
        raise SystemExit("CPA inference key file is empty")
    private.mkdir(mode=0o700)  # Existing state is never overwritten or rotated.
    directory = private / "secrets"
    directory.mkdir(mode=0o700)
    for name in ("postgres_password", "master_key", "salt_key", "ui_password"):
        prefix = "sk-" if name == "master_key" else "Aa1!"
        save(directory / name, prefix + secrets.token_urlsafe(32) + "\n")
    save(directory / "cpa_api_key", key)
    save(
        private / "candidate.env",
        (
            f"CANDIDATE_SECRETS_DIR={directory}\nCPA_API_BASE={args.cpa_base}\n"
            f"CPA_NETWORK={args.cpa_network}\nCANDIDATE_PORT={args.port}\n"
        ),
    )
    print(f"Private setup created: {private}")


def claims(token):
    # This extracts a server-issued login response for use with the native API;
    # it is not an authentication decision or a replacement token verifier.
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))


def provision(args):
    private = args.private_dir.resolve()
    if private.is_relative_to(ROOT) or private.stat().st_mode & 0o077:
        raise SystemExit("private-dir must be outside the repository with mode 0700")
    target = private / "fixture.json"
    if target.exists():
        raise SystemExit("fixture already exists; reuse it rather than reissue keys")
    parsed = urlsplit(args.base_url)
    if parsed.hostname not in ("127.0.0.1", "localhost") or parsed.scheme != "http":
        raise SystemExit("fixture setup accepts only the isolated loopback HTTP POC")
    master = (private / "secrets/master_key").read_text().strip()

    def call(method, path, data=None, key=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        request = Request(
            args.base_url + path,
            method=method,
            headers=headers,
            data=json.dumps(data).encode() if data is not None else None,
        )
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            # Do not echo server error bodies: they may contain credentials/content.
            raise SystemExit(f"{method} {path.split('?')[0]} returned HTTP {error.code}") from None

    # The native login creates the administrator row needed by invitation FKs.
    call(
        "POST",
        "/v2/login",
        {
            "username": "candidate-admin",
            "password": (private / "secrets/ui_password").read_text().strip(),
        },
    )
    fixture = {"base_url": args.base_url, "model": MODEL, "users": {}}
    partial = private / "fixture.partial.json"
    if partial.exists():
        raise SystemExit("partial fixture exists; inspect privately before retrying setup")
    save(partial, json.dumps(fixture))
    for label in ("A", "B"):
        user_id = f"candidate-user-{label.lower()}"
        email = f"{user_id}@example.invalid"
        password = "Aa1!" + secrets.token_urlsafe(28)
        policy = {"models": [MODEL], "rpm_limit": 10, "tpm_limit": 20000}
        call(
            "POST",
            "/user/new",
            {
                "user_id": user_id,
                "user_email": email,
                "user_role": "internal_user",
                "auto_create_key": False,
                **policy,
            },
            master,
        )
        user = {"user_id": user_id, "email": email, "password": password, "keys": {}}
        fixture["users"][label] = user
        partial.write_text(json.dumps(fixture, indent=2))
        invite = call("POST", "/invitation/new", {"user_id": user_id}, master)
        token = call("GET", "/onboarding/get_token?" + urlencode({"invite_link": invite["id"]}))
        call(
            "POST",
            "/onboarding/claim_token",
            {
                "invitation_link": invite["id"],
                "user_id": user_id,
                "password": password,
            },
            claims(token["token"])["key"],
        )
        login = call("POST", "/v2/login", {"username": email, "password": password})
        session = claims(login["token"])
        if session["user_role"] != "internal_user" or session["premium_user"]:
            raise SystemExit("fixture requires community ordinary-user login")
        user.update(ui_token=login["token"], session_key=session["key"])
        for key_label in ("A", "A2") if label == "A" else ("B",):
            key = call(
                "POST",
                "/key/generate",
                {
                    "user_id": user_id,
                    "key_alias": "candidate-" + key_label.lower(),
                    **policy,
                },
                master,
            )
            if key["user_id"] != user_id:
                raise SystemExit("native key owner differs from requested owner")
            user["keys"][key_label] = key["key"]
            partial.write_text(json.dumps(fixture, indent=2))
        print(f"{label}: native internal_user login and owned keys provisioned")
    partial.rename(target)
    print(f"Private fixture: {target}")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create new private secrets; refuses existing state")
    init.add_argument("--private-dir", type=Path, required=True)
    init.add_argument("--cpa-key-file", type=Path, required=True)
    init.add_argument("--cpa-network", required=True)
    init.add_argument("--cpa-base", required=True)
    init.add_argument("--port", type=int, default=14000)
    fixture = sub.add_parser("fixture", help="native onboarding and A/A2/B keys on a fresh POC")
    fixture.add_argument("--private-dir", type=Path, required=True)
    fixture.add_argument("--base-url", default="http://127.0.0.1:14000")
    args = parser.parse_args()
    try:
        (initialize if args.command == "init" else provision)(args)
    except OSError as error:
        print(f"candidate setup failed ({type(error).__name__}); state preserved", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
