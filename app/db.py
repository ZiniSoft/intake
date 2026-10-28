from __future__ import annotations

from pathlib import Path
import re

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Base

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        if settings.database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            engine_options = {"connect_args": connect_args}
            if settings.database_url.endswith(":memory:"):
                engine_options["poolclass"] = StaticPool
            _engine = create_engine(settings.database_url, future=True, **engine_options)
        else:
            _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    return _engine


def get_session() -> Session:
    return Session(get_engine())


_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _split_sql_statements(script: str) -> list[str]:
    """Split a PostgreSQL script without treating semicolons in literals or comments as terminators."""
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    dollar_quote: str | None = None
    line_comment = False
    block_comment_depth = 0
    index = 0

    while index < len(script):
        char = script[index]
        following = script[index + 1] if index + 1 < len(script) else ""

        if line_comment:
            buffer.append(char)
            index += 1
            if char == "\n":
                line_comment = False
            continue

        if block_comment_depth:
            if char == "/" and following == "*":
                buffer.extend((char, following))
                block_comment_depth += 1
                index += 2
            elif char == "*" and following == "/":
                buffer.extend((char, following))
                block_comment_depth -= 1
                index += 2
            else:
                buffer.append(char)
                index += 1
            continue

        if dollar_quote is not None:
            if script.startswith(dollar_quote, index):
                buffer.append(dollar_quote)
                index += len(dollar_quote)
                dollar_quote = None
            else:
                buffer.append(char)
                index += 1
            continue

        if quote is not None:
            buffer.append(char)
            index += 1
            if char == quote:
                if index < len(script) and script[index] == quote:
                    buffer.append(script[index])
                    index += 1
                else:
                    quote = None
            continue

        if char == "-" and following == "-":
            buffer.extend((char, following))
            line_comment = True
            index += 2
            continue
        if char == "/" and following == "*":
            buffer.extend((char, following))
            block_comment_depth = 1
            index += 2
            continue
        if char in {"'", '"'}:
            buffer.append(char)
            quote = char
            index += 1
            continue
        if char == "$":
            match = _DOLLAR_QUOTE.match(script, index)
            if match:
                dollar_quote = match.group(0)
                buffer.append(dollar_quote)
                index = match.end()
                continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _execute_sql_script(connection, script: str) -> None:
    for statement in _split_sql_statements(script):
        connection.execute(text(statement))


def run_migrations() -> None:
    engine = get_engine()
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
        return
    if engine.dialect.name != "postgresql":
        raise RuntimeError(f"Unsupported database dialect: {engine.dialect.name}")

    migration_dir = Path(__file__).resolve().parent / "migrations" / "postgresql"
    # All runtime roles may start together on a cold Compose boot. A session-level
    # advisory lock serializes extension/schema creation across those processes.
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(7046029254386353131)"))
        connection.commit()
        try:
            with connection.begin():
                connection.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS schema_migrations "
                        "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                    )
                )
            for migration in sorted(migration_dir.glob("*.sql")):
                with connection.begin():
                    applied = connection.execute(
                        text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                        {"version": migration.name},
                    ).first()
                    if applied is not None:
                        continue
                    _execute_sql_script(connection, migration.read_text(encoding="utf-8"))
                    connection.execute(
                        text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                        {"version": migration.name},
                    )
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(7046029254386353131)"))
            connection.commit()


def init_db() -> None:
    run_migrations()
