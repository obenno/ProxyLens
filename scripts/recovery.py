#!/usr/bin/env python3
"""Owner-only recovery sets; credentials enter through private files, never arguments.

Logical PostgreSQL backups cover one database, not a consistent multi-store snapshot.
Run from a frozen matching checkout with the hash-locked Python environment.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    "docker.io/library/postgres@sha256:"
    "858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27"
)
VOLUMES = ("postgres_data", "keycloak_db_data", "cpa_config", "cpa_auth", "cpamp_data")


class RecoveryError(Exception):
    """Fixed diagnostic only; never include subprocess/database error text."""


def checked_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RecoveryError("symlink paths are not allowed")
    return path


def new_directory(path: Path) -> Path:
    path = checked_path(path)
    # No parents=True: require an explicitly provisioned parent, no existing target.
    try:
        path.mkdir(mode=0o700)
    except OSError:
        raise RecoveryError(
            "destination must be a new directory under an existing parent"
        ) from None
    return path


def private_write(path: Path, data: bytes):
    fd = os.open(checked_path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)


def private_path(path: Path, *, directory: bool = False):
    path = checked_path(path)
    info = path.stat()
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_type or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RecoveryError("recovery paths must be owner-only regular files/directories")
    return path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_manifest(directory: Path, metadata: dict, files: list[Path]):
    manifest = metadata | {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "files": {path.name: digest(path) for path in files},
    }
    private_write(directory / "manifest.json", json.dumps(manifest, indent=2).encode())


def validate(directory: Path) -> dict:
    directory = private_path(directory, directory=True)
    manifest = json.loads(private_path(directory / "manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise RecoveryError("invalid recovery manifest")
    files = manifest.get("files")
    if manifest.get("format") != 1 or not isinstance(files, dict) or not files:
        raise RecoveryError("invalid recovery manifest")
    for name, expected in files.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise RecoveryError("invalid recovery member name")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RecoveryError("invalid recovery checksum")
        if digest(private_path(directory / name)) != expected:
            raise RecoveryError("recovery checksum mismatch")
    return manifest


def connection_file(path: Path) -> dict:
    values = json.loads(private_path(path).read_text())
    allowed = {"host", "port", "dbname", "user", "password", "sslmode", "sslrootcert"}
    if not isinstance(values, dict) or not values.keys() <= allowed or "dbname" not in values:
        raise RecoveryError("invalid PostgreSQL connection file")
    return values


def command(args, *, env=None, stdin=None, stdout=subprocess.PIPE) -> bytes:
    result = subprocess.run(args, env=env, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE)
    if result.returncode:
        raise RecoveryError("recovery subprocess failed; no credentials or server detail emitted")
    return result.stdout or b""


def pg_command(args, executable, options, values, *, stdin=None, stdout=subprocess.PIPE):
    names = {
        "host": "PGHOST",
        "port": "PGPORT",
        "dbname": "PGDATABASE",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update({names[k]: str(v) for k, v in values.items()})
    env["PGCONNECT_TIMEOUT"] = "5"
    prefix = []
    if args.pg_container:
        # Container must be the same PostgreSQL server named by connection_file.
        env.update(PGHOST="127.0.0.1", PGPORT="5432")
        prefix = [args.engine, "exec", "-i"]
        for name in (*names.values(), "PGCONNECT_TIMEOUT"):
            if name in env:
                prefix += ["--env", name]  # Values never enter the process argument list.
        prefix += [args.pg_container]
    return command(prefix + [executable, *options], env=env, stdin=stdin, stdout=stdout)


def schema_fingerprint(conn) -> list:
    """Safe counts plus private content digests; no row data printed or retained."""
    tables = conn.execute(
        "SELECT schemaname, tablename FROM pg_tables "
        "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY schemaname, tablename"
    ).fetchall()
    results = []
    for schema, table in tables:
        query = sql.SQL(
            'SELECT row_to_json(t)::text FROM {}.{} t ORDER BY row_to_json(t)::text COLLATE "C"'
        ).format(sql.Identifier(schema), sql.Identifier(table))
        hashed = hashlib.sha256()
        count = 0
        with conn.cursor(name="recovery_fingerprint") as cursor:
            cursor.execute(query)
            for (row,) in cursor:
                encoded = row.encode()
                hashed.update(len(encoded).to_bytes(8, "big"))
                hashed.update(encoded)
                count += 1
        results.append(
            {"schema": schema, "table": table, "rows": count, "sha256": hashed.hexdigest()}
        )
    return results


def verify_server(args, values, conn):
    if args.pg_container:
        identity = str(
            conn.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]
        )
        actual = (
            pg_command(
                args,
                "psql",
                [
                    "--no-psqlrc",
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "SELECT system_identifier FROM pg_control_system()",
                ],
                values,
            )
            .decode()
            .strip()
        )
        if actual != identity:
            raise RecoveryError("PostgreSQL utility container is not the selected server")
    client = pg_command(args, "pg_dump", ["--version"], values).decode().strip()
    match = re.search(r"PostgreSQL\) (\d+)\.", client)
    if not match or int(match[1]) != conn.info.server_version // 10000:
        raise RecoveryError("PostgreSQL utility major must match the selected server")
    return client


def backup_postgres(args):
    values = connection_file(args.connection_file)
    destination = new_directory(args.destination)
    commit = command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip()
    # Pin source and dependencies beside the archive, without copying .env/secrets.
    files = []
    for name in ("compose.yaml", "requirements.lock", "requirements-dev.lock"):
        target = destination / name
        private_write(target, (ROOT / name).read_bytes())
        files.append(target)
    dump = destination / "postgres.dump"
    private_write(dump, b"")
    with psycopg.connect(**values, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET TIME ZONE 'UTC'")
        client = verify_server(args, values, conn)
        version = conn.info.server_version
        snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        with dump.open("wb") as output:
            pg_command(
                args,
                "pg_dump",
                ["--format=custom", "--no-owner", "--no-acl", "--snapshot", snapshot],
                values,
                stdout=output,
            )
        fingerprint = schema_fingerprint(conn)
    private_write(destination / "fingerprint.json", json.dumps(fingerprint).encode())
    files += [dump, destination / "fingerprint.json"]
    write_manifest(
        destination,
        {
            "kind": "postgres",
            "git_commit": commit,
            "checkout_dirty": bool(command(["git", "-C", str(ROOT), "status", "--porcelain"])),
            "server_version": version,
            "server_major": version // 10000,
            "dump_client": client,
            "source_database": values["dbname"],
            "matching_set": args.recovery_set,
            "scope": "one-database; separate coordinated secrets and other-store backup required",
        },
        files,
    )
    validate(destination)


def restore_postgres(args):
    manifest = validate(args.backup)
    if manifest.get("kind") != "postgres":
        raise RecoveryError("not a PostgreSQL recovery set")
    required = {
        "postgres.dump",
        "fingerprint.json",
        "compose.yaml",
        "requirements.lock",
        "requirements-dev.lock",
    }
    if not required <= manifest["files"].keys():
        raise RecoveryError("incomplete PostgreSQL recovery set")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", args.database):
        raise RecoveryError("new database name must be a lowercase identifier")
    values = connection_file(args.connection_file)
    if args.database in {
        values["dbname"],
        manifest.get("source_database"),
        "postgres",
        "template0",
        "template1",
    }:
        raise RecoveryError("restore requires a distinct new database")
    # New private report directory is also required; never clobber current artifacts.
    report = new_directory(args.destination)
    with psycopg.connect(**values, connect_timeout=5, autocommit=True) as conn:
        verify_server(args, values, conn)
        if conn.info.server_version // 10000 != manifest["server_major"]:
            raise RecoveryError("restore requires matching PostgreSQL major version")
        if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (args.database,)).fetchone():
            raise RecoveryError("restore database already exists")
        # CREATE DATABASE, without IF NOT EXISTS, also protects against a creation race.
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(args.database))
        )
    target = values | {"dbname": args.database}
    with (args.backup / "postgres.dump").open("rb") as source:
        pg_command(
            args,
            "pg_restore",
            [
                "--dbname",
                args.database,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
            ],
            target,
            stdin=source,
        )
    with psycopg.connect(**target, connect_timeout=5) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        actual = schema_fingerprint(conn)
    expected = json.loads((args.backup / "fingerprint.json").read_text())
    if actual != expected:
        raise RecoveryError("restored row fingerprint mismatch; keep isolated for inspection")
    private_write(
        report / "validation.json",
        json.dumps(
            {
                "restored": True,
                "fingerprints_match": True,
                "tables": len(actual),
                "rows": sum(table["rows"] for table in actual),
                "git_commit": manifest["git_commit"],
                "matching_set": manifest["matching_set"],
                "checked_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        ).encode(),
    )


def validate_tar(path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise RecoveryError("unsafe archive member")
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise RecoveryError("special archive members are not supported")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts:
                    raise RecoveryError("unsafe archive link")


def volume_inspect(engine, name):
    value = json.loads(command([engine, "volume", "inspect", name]))
    if len(value) != 1 or value[0]["Name"] != name:
        raise RecoveryError("volume identity mismatch")
    return value[0]


def ensure_quiesced(engine, names, mountpoints):
    ids = command([engine, "ps", "-aq"]).decode().split()
    if not ids:
        return
    # Inspect privately; engine output may include application credentials.
    for container in json.loads(command([engine, "inspect", *ids])):
        mounted = {mount.get("Name") for mount in container.get("Mounts", [])}
        bound = any(
            mount.get("Source", "") == source or mount.get("Source", "").startswith(source + "/")
            for mount in container.get("Mounts", [])
            for source in mountpoints
        )
        if (mounted.intersection(names) or bound) and container.get("State", {}).get("Running"):
            raise RecoveryError("cold backup requires all source-volume containers stopped")


def backup_foundation(args):
    if not args.confirm_quiesced:
        raise RecoveryError("quiescence confirmation required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]+", args.project):
        raise RecoveryError("invalid source project")
    names = [f"{args.project}_{suffix}" for suffix in VOLUMES]
    volumes = [volume_inspect(args.engine, name) for name in names]
    mountpoints = [volume["Mountpoint"] for volume in volumes]
    target = checked_path(args.destination)
    protected = [checked_path(args.secrets_directory), *(Path(p) for p in mountpoints)]
    if any(target == path or path in target.parents for path in protected):
        raise RecoveryError("backup destination cannot be inside source state")
    ensure_quiesced(args.engine, names, mountpoints)
    destination = new_directory(args.destination)
    files = []
    for suffix, volume in zip(VOLUMES, volumes, strict=True):
        archive = destination / f"{suffix}.tgz"
        private_write(archive, b"")
        # Host-path bind avoids named-volume copy-up on the read-only source.
        source = volume["Mountpoint"]
        with archive.open("wb") as output:
            command(
                [
                    args.engine,
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--read-only",
                    "--user",
                    "0",
                    "--mount",
                    f"type=bind,src={source},dst=/source,readonly",
                    "--entrypoint",
                    "tar",
                    HELPER,
                    "--atime-preserve=system",
                    "--numeric-owner",
                    "-czpf",
                    "-",
                    "-C",
                    "/source",
                    ".",
                ],
                stdout=output,
            )
        validate_tar(archive)
        files.append(archive)
    secrets = private_path(args.secrets_directory, directory=True)
    archive = destination / "secrets.tgz"
    private_write(archive, b"")
    with tarfile.open(archive, "w:gz") as output:
        output.add(secrets, arcname="secrets", recursive=True)
    validate_tar(archive)
    files.append(archive)
    # Environment is part of the same private set, never printed by Compose config.
    environment = private_path(args.environment_file)
    private_write(destination / "environment", environment.read_bytes())
    files.append(destination / "environment")
    for name in ("compose.yaml", "requirements.lock", "requirements-dev.lock"):
        target = destination / name
        private_write(target, (ROOT / name).read_bytes())
        files.append(target)
    # The operator supplies exact app image IDs and upstream pins as a private JSON file.
    images = json.loads(private_path(args.images_file).read_text())
    if (
        not isinstance(images, dict)
        or not images
        or not {
            "postgres",
            "keycloak-db",
            "keycloak",
            "cliproxyapi",
            "cpamp",
            "api",
            "gateway",
            "worker",
            "cpa-init",
        }
        <= images.keys()
        or not all(
            isinstance(v, str) and ("@sha256:" in v or re.fullmatch(r"sha256:[0-9a-f]{64}", v))
            for v in images.values()
        )
    ):
        raise RecoveryError("immutable image identities required")
    private_write(destination / "images.json", json.dumps(images).encode())
    files.append(destination / "images.json")
    ensure_quiesced(args.engine, names, mountpoints)
    write_manifest(
        destination,
        {
            "kind": "foundation",
            "git_commit": command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip(),
            "helper_image": HELPER,
            "matching_set": args.recovery_set,
            "source_project": args.project,
            "scope": "five foundation stores; external Langfuse requires its own matching set",
        },
        files,
    )
    validate(destination)


def restore_foundation(args):
    manifest = validate(args.backup)
    if manifest.get("kind") != "foundation" or manifest.get("helper_image") != HELPER:
        raise RecoveryError("unsupported foundation recovery set")
    required = {f"{suffix}.tgz" for suffix in VOLUMES} | {
        "secrets.tgz",
        "environment",
        "images.json",
        "compose.yaml",
        "requirements.lock",
        "requirements-dev.lock",
    }
    if not required <= manifest["files"].keys():
        raise RecoveryError("incomplete foundation recovery set")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]+", args.project):
        raise RecoveryError("invalid destination project")
    if args.project == manifest["source_project"]:
        raise RecoveryError("restore requires a new project")
    for name in required:
        if name.endswith(".tgz"):
            validate_tar(args.backup / name)
    existing = set(command([args.engine, "volume", "ls", "-q"]).decode().split())
    names = [f"{args.project}_{suffix}" for suffix in VOLUMES]
    if existing.intersection(names):
        raise RecoveryError("restore requires new volumes")
    target = checked_path(args.destination)
    backup = checked_path(args.backup)
    if target == backup or backup in target.parents:
        raise RecoveryError("restore destination cannot be inside the recovery set")
    destination = new_directory(args.destination)
    # Explicit plan persists before creation; failed partial restores are never reused.
    private_write(destination / "restore-plan.json", json.dumps({"volumes": names}).encode())
    for suffix, name in zip(VOLUMES, names, strict=True):
        # Unique label proves this invocation created it even if a name races creation.
        token = uuid4().hex
        command([args.engine, "volume", "create", "--label", f"proxylens.recovery={token}", name])
        volume = volume_inspect(args.engine, name)
        if volume.get("Labels", {}).get("proxylens.recovery") != token:
            raise RecoveryError("destination volume creation race")
        with (args.backup / f"{suffix}.tgz").open("rb") as archive:
            command(
                [
                    args.engine,
                    "run",
                    "--rm",
                    "-i",
                    "--pull=never",
                    "--network=none",
                    "--read-only",
                    "--user",
                    "0",
                    "-v",
                    f"{name}:/target:nocopy",
                    "--entrypoint",
                    "bash",
                    HELPER,
                    "-ceu",
                    'test -z "$(ls -A /target)"; exec tar --numeric-owner -xzpf - -C /target',
                ],
                stdin=archive,
            )
    with tarfile.open(args.backup / "secrets.tgz", "r:gz") as archive:
        archive.extractall(destination, filter="data")
    (destination / "secrets").chmod(0o700)
    for name in required - {f"{suffix}.tgz" for suffix in VOLUMES} - {"secrets.tgz"}:
        private_write(destination / name, (args.backup / name).read_bytes())
    # No service is started; operator validates pins, storage integrity and isolation first.


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("backup", type=Path)
    for name in ("backup-postgres", "restore-postgres"):
        item = sub.add_parser(name)
        item.add_argument("--connection-file", type=Path, required=True)
        item.add_argument("--destination", type=Path, required=True)
        item.add_argument(
            "--pg-container", help="optional same-server PostgreSQL utility container"
        )
        item.add_argument("--engine", choices=("docker", "podman"), default="docker")
        if name == "backup-postgres":
            item.add_argument("--recovery-set", required=True, help="nonsecret matching-set label")
        else:
            item.add_argument("--backup", type=Path, required=True)
            item.add_argument(
                "--database", required=True, help="new database; existing names refused"
            )
    for name in ("backup-foundation", "restore-foundation"):
        item = sub.add_parser(name)
        item.add_argument("--engine", choices=("docker", "podman"), default="docker")
        item.add_argument("--project", required=True)
        item.add_argument("--destination", type=Path, required=True)
        if name == "backup-foundation":
            item.add_argument("--confirm-quiesced", action="store_true")
            item.add_argument("--secrets-directory", type=Path, required=True)
            item.add_argument("--environment-file", type=Path, required=True)
            item.add_argument("--images-file", type=Path, required=True)
            item.add_argument("--recovery-set", required=True)
        else:
            item.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate(args.backup)
        elif args.command == "backup-postgres":
            backup_postgres(args)
        elif args.command == "restore-postgres":
            restore_postgres(args)
        elif args.command == "backup-foundation":
            backup_foundation(args)
        else:
            restore_foundation(args)
    except (RecoveryError, OSError, ValueError, psycopg.Error):
        # No error values: server/client exception text can contain credentials/data.
        print("Recovery failed; destinations preserved for private inspection.", file=sys.stderr)
        return 1
    print("Recovery operation verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
