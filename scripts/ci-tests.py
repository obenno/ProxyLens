#!/usr/bin/env python3
"""Run the complete suite against new isolated PostgreSQL databases; skips fail CI."""

import os
import secrets
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlencode
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


def main():
    os.umask(0o077)
    admin = conninfo_to_dict(os.environ["PROXYLENS_CI_DATABASE_URL"])
    variables = (
        "PROXYLENS_TEST_DATABASE_URL",
        "PROXYLENS_RESOURCES_TEST_DSN",
        "PROXYLENS_OPS_TEST_DSN",
        "PROXYLENS_GATEWAY_TEST_DSN",
        "PROXYLENS_PROJECTION_TEST_DSN",
        "PROXYLENS_EXPORTER_TEST_DSN",
    )
    created = []
    env = dict(os.environ)
    try:
        with psycopg.connect(**admin, autocommit=True) as conn:
            for variable in variables:
                name = "ci_" + uuid4().hex
                conn.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
                )
                created.append(name)
                # Gateway's fixture consumes a URL and requires a nonempty secret
                # file even on the ephemeral trust-authenticated CI service.
                password = admin.get("password") or secrets.token_hex(16)
                user = quote(admin.get("user", "postgres"), safe="")
                host = admin.get("host", "127.0.0.1")
                port = admin.get("port", "5432")
                query = urlencode(
                    {
                        k: v
                        for k, v in admin.items()
                        if k not in {"host", "port", "user", "password", "dbname"}
                    }
                )
                env[variable] = (
                    f"postgresql://{user}:{quote(password, safe='')}@{host}:{port}/{name}"
                    + (f"?{query}" if query else "")
                )
        with tempfile.TemporaryDirectory(prefix="proxylens-ci-") as directory:
            report = Path(directory) / "pytest.xml"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}"],
                env=env,
            )
            if result.returncode:
                return result.returncode
            suites = ET.parse(report).getroot().iter("testsuite")
            if any(int(suite.get("skipped", "0")) for suite in suites):
                print("CI requires every PostgreSQL integration test; skipped tests fail.")
                return 1
        return 0
    finally:
        with psycopg.connect(**admin, autocommit=True) as conn:
            for name in created:
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


if __name__ == "__main__":
    raise SystemExit(main())
