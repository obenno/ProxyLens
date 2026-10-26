"""Small PostgreSQL transaction and checksum-verified migration boundary."""

from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class StorageUnavailable(Exception):
    """Storage could not durably complete the operation (no connection details)."""


class Database:
    def __init__(self, dsn: str = "", *, password_file: str | None = None, **connect_options):
        self._dsn = dsn
        self._password_file = password_file
        self._options = {
            "connect_timeout": 3,
            "options": "-c statement_timeout=5000 -c lock_timeout=3000",
            **connect_options,
        }

    @asynccontextmanager
    async def transaction(self):
        try:
            options = dict(self._options)
            if self._password_file is not None:
                options["password"] = Path(self._password_file).read_text().strip()
            async with await psycopg.AsyncConnection.connect(
                self._dsn, row_factory=dict_row, **options
            ) as connection:
                yield connection
        except (psycopg.Error, OSError, TimeoutError):
            raise StorageUnavailable("authorization storage unavailable") from None

    async def migrate(self, directory: Path | None = None):
        directory = directory or Path(__file__).parent / "migrations"
        async with self.transaction() as conn:
            # Serialize startup migrations across API/gateway/worker processes.
            await conn.execute("SELECT pg_advisory_xact_lock(706769001)")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS proxylens_migrations "
                "(name text PRIMARY KEY, checksum text NOT NULL, "
                "applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"
            )
            for path in sorted(directory.rglob("*.sql")):
                name = str(path.relative_to(directory))
                script = path.read_text()
                checksum = sha256(script.encode()).hexdigest()
                found = await (
                    await conn.execute(
                        "SELECT checksum FROM proxylens_migrations WHERE name = %s", (name,)
                    )
                ).fetchone()
                if found:
                    if found["checksum"] != checksum:
                        raise StorageUnavailable("applied migration checksum mismatch")
                    continue
                await conn.execute(script)
                await conn.execute(
                    "INSERT INTO proxylens_migrations(name, checksum) VALUES (%s, %s)",
                    (name, checksum),
                )
