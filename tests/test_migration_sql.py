from pathlib import Path

from app.db import _split_sql_statements


def test_sql_splitter_keeps_semicolons_inside_postgresql_syntax() -> None:
    script = """
-- A comment with a semicolon; is still one comment.
UPDATE example SET note = 'retired; historical record kept' WHERE id = 1;
/* A block comment; with a nested /* inner; comment */ still here. */
DO $migration$
BEGIN
    RAISE NOTICE 'one;two';
END
$migration$;
SELECT "column;name" FROM example;
"""

    statements = _split_sql_statements(script)

    assert len(statements) == 3
    assert "'retired; historical record kept'" in statements[0]
    assert "RAISE NOTICE 'one;two';" in statements[1]
    assert 'SELECT "column;name"' in statements[2]


def test_plane_retirement_migration_is_split_into_complete_statements() -> None:
    migration = Path("app/migrations/postgresql/001_baseline.sql").read_text(encoding="utf-8")

    statements = _split_sql_statements(migration)

    assert statements
    assert all(statement.count("'") % 2 == 0 for statement in statements if "Plane integration retired" in statement or "ROUTE_RETIRED" in statement)
    assert any("Plane integration retired, historical record kept" in statement for statement in statements)
