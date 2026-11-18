"""
sync_web_accessibility_schema.py - one-off maintenance script.

Why this exists: the accessibility_web module has no Alembic/migrations,
and Base.metadata.create_all() (called on every app startup - see
main.py's lifespan) only creates tables that don't exist yet. It never
ALTERs a table that's already there. If a web_accessibility_* table was
created from an older version of its model, columns added to the model
afterward silently do not exist in the live database - which is exactly
what caused:

    pymysql.err.OperationalError: (1054, "Unknown column 'crawl_frequency'
    in 'field list'")

when POST /websites/{id}/scan tried to INSERT into web_accessibility_scans.

What it does: compares each web_accessibility_* model's declared columns
against what actually exists in the connected database (per .env) and
prints (or, with --apply, runs) ALTER TABLE ... ADD COLUMN statements for
whatever is missing. A table that doesn't exist at all yet is left alone -
create_all() already handles that case correctly on the next app startup.

Usage (from the orion_backend project root, with your venv active):
    python scripts/sync_web_accessibility_schema.py            # dry run: prints SQL, changes nothing
    python scripts/sync_web_accessibility_schema.py --apply    # actually runs the ALTER TABLE statements

Safe to re-run - a table already in sync prints nothing to do.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect
from sqlalchemy.schema import CreateColumn

from src.core.database import engine

# Import every web_accessibility_* model so their tables are registered.
from src.modules.accessibility_web.models.web_accessibility_issues_model import (
    WebAccessibilityIssuesModel,
)
from src.modules.accessibility_web.models.web_accessibility_rules_model import (
    WebAccessibilityRulesModel,
)
from src.modules.accessibility_web.models.web_accessibility_scans_model import (
    WebAccessibilityScansModel,
)
from src.modules.accessibility_web.models.web_accessibility_websites_model import (
    WebAccessibilityWebsiteModel,
)

MODELS = [
    WebAccessibilityWebsiteModel,
    WebAccessibilityScansModel,
    WebAccessibilityIssuesModel,
    WebAccessibilityRulesModel,
]


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def build_alter_statements(inspector, model) -> list[str]:
    table = model.__table__
    table_name = table.name

    if not inspector.has_table(table_name):
        # Doesn't exist yet - create_all() (already called on every app
        # startup) will create it correctly from the current model.
        # Nothing for this script to do.
        return []

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    statements = []

    for column in table.columns:
        if column.name in existing_columns:
            continue

        if column.primary_key:
            # Should not happen in practice - the PK is always present
            # from the table's original creation. Adding a PK after the
            # fact isn't safe to automate; flag it for a human instead.
            print(
                f"  ! {table_name}.{column.name} is a primary key column "
                f"missing from the live table - skipping, needs manual attention"
            )
            continue

        column_ddl = str(CreateColumn(column).compile(dialect=engine.dialect))

        # CreateColumn only emits a DEFAULT for server_default. A NOT NULL
        # column whose default is Python-side only (e.g. default=False)
        # would otherwise fail to ADD on a table that already has rows -
        # backfill existing rows with the same literal the model's default
        # would produce for a new row.
        if (
            not column.nullable
            and "DEFAULT" not in column_ddl.upper()
            and column.default is not None
            and column.default.is_scalar
        ):
            column_ddl = f"{column_ddl} DEFAULT {_sql_literal(column.default.arg)}"

        statements.append(f"ALTER TABLE {table_name} ADD COLUMN {column_ddl};")

    return statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually run the ALTER TABLE statements (default: dry run - print only)",
    )
    args = parser.parse_args()

    inspector = inspect(engine)
    all_statements = []

    for model in MODELS:
        statements = build_alter_statements(inspector, model)
        if statements:
            print(f"\n-- {model.__table__.name} --")
            for stmt in statements:
                print(stmt)
            all_statements.extend(statements)

    if not all_statements:
        print("All web_accessibility_* tables already match their models. Nothing to do.")
        return

    if not args.apply:
        print(f"\n{len(all_statements)} statement(s) above would run. Re-run with --apply to execute them.")
        return

    print(f"\nApplying {len(all_statements)} statement(s)...")
    with engine.begin() as conn:
        for stmt in all_statements:
            print(f"  running: {stmt}")
            conn.exec_driver_sql(stmt)
    print("Done.")


if __name__ == "__main__":
    main()
