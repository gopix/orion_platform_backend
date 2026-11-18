"""
migrate_web_accessibility_pages.py - one-off migration for the new
web_accessibility_pages table (Website 1:N Page 1:N Scan 1:N Issue - see
the review comment this implements, and web_accessibility_pages_model.py).

Why one combined script instead of splitting DDL into
sync_web_accessibility_schema.py and data into a separate backfill script:
ordering matters and is easy to get wrong by hand. web_accessibility_scans
.page_id must exist (nullable) before it can be backfilled; the FK
constraint on web_accessibility_issues.page_id can only be added AFTER
that column's legacy placeholder values (scan.id, from before the page
model existed - see web_accessibility_issues_model.py's class docstring)
have been overwritten with real pages.id values, or MySQL rejects the
constraint against existing data that doesn't satisfy it. This script runs
all of it, strictly in the safe order, in one place:

    1. CREATE TABLE web_accessibility_pages if missing (safe/idempotent -
       Base.metadata.create_all() never touches an existing table)
    2. ALTER TABLE web_accessibility_scans ADD COLUMN page_id (nullable -
       safe on a populated table; existing rows just get NULL until step 3)
    3. Backfill: one Page row per distinct (website_id, url) seen in
       existing scans; point every scan at its page; repoint every issue
       at its scan's page
    4. ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY on both
       scans.page_id and issues.page_id -> pages.id (only safe now that
       every row holds a valid pages.id)

Usage (from the orion_backend project root, with your venv active):
    python scripts/migrate_web_accessibility_pages.py            # dry run: prints a plan, changes nothing
    python scripts/migrate_web_accessibility_pages.py --apply    # actually runs all 4 steps

Dry run is read-only against tables that already exist (scans, issues) -
it does NOT create web_accessibility_pages or touch scans/issues even to
preview, so "nothing was changed" is a literal guarantee, not just "no
data was changed."

Safe to re-run - already-migrated tables/columns/rows/constraints are
detected and skipped. Steps 2 and 4 are DDL (ALTER TABLE); MySQL commits
DDL immediately regardless of a surrounding transaction, so if step 4
fails after step 2/3 already ran, just fix the issue and re-run the whole
script - steps 1-3 will no-op on the retry and step 4 will try again.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, select
from sqlalchemy.schema import CreateColumn

from src.core.database import Base, engine

from src.modules.accessibility_web.models.web_accessibility_issues_model import (
    WebAccessibilityIssuesModel,
)
from src.modules.accessibility_web.models.web_accessibility_pages_model import (
    WebAccessibilityPagesModel,
    hash_page_url,
)
from src.modules.accessibility_web.models.web_accessibility_scans_model import (
    WebAccessibilityScansModel,
)

PAGES_TABLE = WebAccessibilityPagesModel.__table__
SCANS_TABLE = WebAccessibilityScansModel.__table__
ISSUES_TABLE = WebAccessibilityIssuesModel.__table__


def _missing_fk_statements(inspector) -> list[str]:
    """
    Step 4's statements. Only inspects the SOURCE tables (scans, issues) -
    safe to call regardless of whether web_accessibility_pages exists yet.
    """
    statements = []
    for table_name, column_name in [(SCANS_TABLE.name, "page_id"), (ISSUES_TABLE.name, "page_id")]:
        if not inspector.has_table(table_name):
            continue
        existing_fk_columns = set()
        for fk in inspector.get_foreign_keys(table_name):
            existing_fk_columns.update(fk["constrained_columns"])
        if column_name in existing_fk_columns:
            continue
        constraint_name = f"fk_{table_name}_{column_name}"
        statements.append(
            f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} "
            f"FOREIGN KEY ({column_name}) REFERENCES {PAGES_TABLE.name}(id);"
        )
    return statements


def dry_run():
    inspector = inspect(engine)
    pages_exists = inspector.has_table(PAGES_TABLE.name)
    scans_has_page_id = (
        inspector.has_table(SCANS_TABLE.name)
        and "page_id" in {c["name"] for c in inspector.get_columns(SCANS_TABLE.name)}
    )

    with engine.connect() as conn:
        distinct_pages = conn.execute(
            select(SCANS_TABLE.c.website_id, SCANS_TABLE.c.url).distinct()
        ).all()
        total_scans = conn.execute(select(SCANS_TABLE.c.id)).all()
        total_issues = conn.execute(select(ISSUES_TABLE.c.id)).all()
        existing_pages = len(conn.execute(select(PAGES_TABLE.c.id)).all()) if pages_exists else 0

    print(f"web_accessibility_pages table exists: {pages_exists}")
    print(f"web_accessibility_scans.page_id column exists: {scans_has_page_id}")
    print()
    print(f"Distinct (website_id, url) pages among existing scans: {len(distinct_pages)}")
    print(f"  existing Page rows already there: {existing_pages}")
    print(f"  pages that would be created: up to {max(0, len(distinct_pages) - existing_pages)}")
    print(f"Scans that would get page_id set/verified: {len(total_scans)}")
    print(f"Issues that would get page_id repointed: {len(total_issues)}")
    print()

    if not pages_exists:
        print("Would also run: CREATE TABLE web_accessibility_pages (...)")
    if not scans_has_page_id:
        column = SCANS_TABLE.c.page_id
        ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
        print(f"Would also run: ALTER TABLE {SCANS_TABLE.name} ADD COLUMN {ddl};")

    fk_statements = _missing_fk_statements(inspector)
    if fk_statements:
        print("Would also run (only after the backfill in step 3 has actually happened):")
        for stmt in fk_statements:
            print(f"  {stmt}")

    print("\nDry run only - nothing was changed. Re-run with --apply to execute all 4 steps.")


def apply():
    print("Step 1/4: web_accessibility_pages table")
    inspector = inspect(engine)
    if inspector.has_table(PAGES_TABLE.name):
        print("  already exists.")
    else:
        Base.metadata.create_all(bind=engine, tables=[PAGES_TABLE])
        print("  created.")

    print("Step 2/4: web_accessibility_scans.page_id column")
    inspector = inspect(engine)
    existing_columns = {c["name"] for c in inspector.get_columns(SCANS_TABLE.name)}
    if "page_id" in existing_columns:
        print("  already exists.")
    else:
        column = SCANS_TABLE.c.page_id
        ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
        stmt = f"ALTER TABLE {SCANS_TABLE.name} ADD COLUMN {ddl};"
        print(f"  running: {stmt}")
        with engine.begin() as conn:
            conn.exec_driver_sql(stmt)

    print("Step 3/4: backfill Page rows + scans.page_id + issues.page_id")
    stats = _backfill()
    print(
        f"  pages created: {stats['pages_created']} (reused {stats['pages_reused']} existing)"
    )
    print(f"  scans updated: {stats['scans_updated']}")
    print(f"  issues updated: {stats['issues_updated']}")

    print("Step 4/4: FK constraints (scans.page_id, issues.page_id -> pages.id)")
    inspector = inspect(engine)  # re-inspect - scans.page_id may be new since step 2
    fk_statements = _missing_fk_statements(inspector)
    if not fk_statements:
        print("  none missing.")
    else:
        with engine.begin() as conn:
            for stmt in fk_statements:
                print(f"  running: {stmt}")
                conn.exec_driver_sql(stmt)

    print("\nDone.")


def _backfill() -> dict:
    """
    Step 3. Uses SQLAlchemy Core table objects, not raw SQL strings and not
    the ORM session - portable across dialects, and it doesn't need the ORM
    model's Python-side metadata to already agree with a table that may
    have just gained a column in step 2 within this same run.
    """
    stats = {"pages_created": 0, "pages_reused": 0, "scans_updated": 0, "issues_updated": 0}

    with engine.begin() as conn:
        pairs = conn.execute(
            select(SCANS_TABLE.c.website_id, SCANS_TABLE.c.url).distinct()
        ).all()

        for website_id, url in pairs:
            url_hash = hash_page_url(url)
            existing_page = conn.execute(
                select(PAGES_TABLE.c.id).where(
                    PAGES_TABLE.c.website_id == website_id,
                    PAGES_TABLE.c.url_hash == url_hash,
                )
            ).first()

            if existing_page:
                page_id = existing_page[0]
                stats["pages_reused"] += 1
            else:
                result = conn.execute(
                    PAGES_TABLE.insert().values(website_id=website_id, url=url, url_hash=url_hash)
                )
                page_id = result.inserted_primary_key[0]
                stats["pages_created"] += 1

            result = conn.execute(
                SCANS_TABLE.update()
                .where(
                    SCANS_TABLE.c.website_id == website_id,
                    SCANS_TABLE.c.url == url,
                    (SCANS_TABLE.c.page_id.is_(None)) | (SCANS_TABLE.c.page_id != page_id),
                )
                .values(page_id=page_id)
            )
            stats["scans_updated"] += result.rowcount

        # Repoint every issue at its scan's (now-correct) page_id. A
        # portable correlated-subquery UPDATE (works on MySQL/SQLite/PG),
        # not MySQL-only UPDATE...JOIN syntax.
        scan_page_pairs = conn.execute(
            select(SCANS_TABLE.c.id, SCANS_TABLE.c.page_id).where(SCANS_TABLE.c.page_id.isnot(None))
        ).all()
        for scan_id, page_id in scan_page_pairs:
            result = conn.execute(
                ISSUES_TABLE.update()
                .where(
                    ISSUES_TABLE.c.scan_id == scan_id,
                    ISSUES_TABLE.c.page_id != page_id,
                )
                .values(page_id=page_id)
            )
            stats["issues_updated"] += result.rowcount

    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually run the migration (default: dry run - print a plan only)",
    )
    args = parser.parse_args()

    if args.apply:
        apply()
    else:
        dry_run()


if __name__ == "__main__":
    main()
