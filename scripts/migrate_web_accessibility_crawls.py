"""
migrate_web_accessibility_crawls.py - one-off migration for the new
web_accessibility_crawls table and web_accessibility_scans.crawl_id
column (see web_accessibility_crawls_model.py and scan_service.py's
module docstring - crawl_website(), the all_pages=true discovery path,
now writes one "crawl run" row and tags every scan it queues with that
row's id, instead of scans from a bulk request being indistinguishable
from a manually-queued one).

Simpler than migrate_web_accessibility_pages.py: no backfill step is
needed. Every EXISTING scan predates this feature and was never part of
a crawl - crawl_id staying NULL for all of them is the correct value,
not a placeholder that needs fixing up. So this is just:

    1. CREATE TABLE web_accessibility_crawls if missing (safe/idempotent -
       Base.metadata.create_all() never touches an existing table)
    2. ALTER TABLE web_accessibility_scans ADD COLUMN crawl_id (nullable -
       safe on a populated table; every existing row gets NULL, which is
       exactly right)
    3. ALTER TABLE web_accessibility_scans ADD CONSTRAINT ... FOREIGN KEY
       (crawl_id) REFERENCES web_accessibility_crawls(id) - safe
       immediately since every existing value is NULL and NULL always
       satisfies a FK

Usage (from the orion_backend project root, with your venv active):
    python scripts/migrate_web_accessibility_crawls.py            # dry run: prints a plan, changes nothing
    python scripts/migrate_web_accessibility_crawls.py --apply    # actually runs all 3 steps

Safe to re-run - already-migrated tables/columns/constraints are detected
and skipped.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect
from sqlalchemy.schema import CreateColumn

from src.core.database import Base, engine

from src.modules.accessibility_web.models.web_accessibility_crawls_model import (
    WebAccessibilityCrawlsModel,
)
from src.modules.accessibility_web.models.web_accessibility_scans_model import (
    WebAccessibilityScansModel,
)

CRAWLS_TABLE = WebAccessibilityCrawlsModel.__table__
SCANS_TABLE = WebAccessibilityScansModel.__table__


def _missing_fk_statement(inspector):
    if not inspector.has_table(SCANS_TABLE.name):
        return None
    existing_fk_columns = set()
    for fk in inspector.get_foreign_keys(SCANS_TABLE.name):
        existing_fk_columns.update(fk["constrained_columns"])
    if "crawl_id" in existing_fk_columns:
        return None
    return (
        f"ALTER TABLE {SCANS_TABLE.name} ADD CONSTRAINT fk_{SCANS_TABLE.name}_crawl_id "
        f"FOREIGN KEY (crawl_id) REFERENCES {CRAWLS_TABLE.name}(id);"
    )


def dry_run():
    inspector = inspect(engine)
    crawls_exists = inspector.has_table(CRAWLS_TABLE.name)
    scans_has_crawl_id = (
        inspector.has_table(SCANS_TABLE.name)
        and "crawl_id" in {c["name"] for c in inspector.get_columns(SCANS_TABLE.name)}
    )

    print(f"web_accessibility_crawls table exists: {crawls_exists}")
    print(f"web_accessibility_scans.crawl_id column exists: {scans_has_crawl_id}")
    print()

    if not crawls_exists:
        print("Would also run: CREATE TABLE web_accessibility_crawls (...)")
    if not scans_has_crawl_id:
        column = SCANS_TABLE.c.crawl_id
        ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
        print(f"Would also run: ALTER TABLE {SCANS_TABLE.name} ADD COLUMN {ddl};")

    fk_statement = _missing_fk_statement(inspector)
    if fk_statement:
        print("Would also run (only after the table/column above exist):")
        print(f"  {fk_statement}")

    print("\nDry run only - nothing was changed. Re-run with --apply to execute all 3 steps.")


def apply():
    print("Step 1/3: web_accessibility_crawls table")
    inspector = inspect(engine)
    if inspector.has_table(CRAWLS_TABLE.name):
        print("  already exists.")
    else:
        Base.metadata.create_all(bind=engine, tables=[CRAWLS_TABLE])
        print("  created.")

    print("Step 2/3: web_accessibility_scans.crawl_id column")
    inspector = inspect(engine)
    existing_columns = {c["name"] for c in inspector.get_columns(SCANS_TABLE.name)}
    if "crawl_id" in existing_columns:
        print("  already exists.")
    else:
        column = SCANS_TABLE.c.crawl_id
        ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
        stmt = f"ALTER TABLE {SCANS_TABLE.name} ADD COLUMN {ddl};"
        print(f"  running: {stmt}")
        with engine.begin() as conn:
            conn.exec_driver_sql(stmt)

    print("Step 3/3: FK constraint (scans.crawl_id -> crawls.id)")
    inspector = inspect(engine)  # re-inspect - crawl_id may be new since step 2
    fk_statement = _missing_fk_statement(inspector)
    if not fk_statement:
        print("  already present.")
    else:
        with engine.begin() as conn:
            print(f"  running: {fk_statement}")
            conn.exec_driver_sql(fk_statement)

    print("\nDone.")


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
