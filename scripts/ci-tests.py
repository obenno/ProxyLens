#!/usr/bin/env python3
"""Run the complete suite against new isolated PostgreSQL databases; skips fail CI."""

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def main():
    admin = conninfo_to_dict(os.environ["PROXYLENS_CI_DATABASE_URL"])
    variables = (
        "PROXYLENS_TEST_DATABASE_URL",
        "PROXYLENS_RESOURCES_TEST_DSN",
        "PROXYLENS_OPS_TEST_DSN",
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
                env[variable] = make_conninfo(**(admin | {"dbname": name}))
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
