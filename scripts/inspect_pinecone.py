"""Inspect what the pipeline stored in Pinecone for a given project.

Reads key / index / region from your .env (via settings). Prints index stats,
then the stored vector IDs and their metadata for the project's namespace, with
a short preview of each embedding.

    python scripts/inspect_pinecone.py            # inspect project 3 (default)
    python scripts/inspect_pinecone.py 5          # inspect project 5
    python scripts/inspect_pinecone.py 3 --reset  # delete project 3's namespace, then inspect
"""
import sys
from pathlib import Path

# Make the repo root importable when run as `python scripts/inspect_pinecone.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pinecone import Pinecone

from src.core.config import settings


def _parse_args() -> tuple[int, bool]:
    """Return (project_id, reset). Accepts the id and an optional --reset flag."""
    args = sys.argv[1:]
    reset = "--reset" in args
    positional = [a for a in args if not a.startswith("-")]
    project_id = int(positional[0]) if positional else 3
    return project_id, reset


def main() -> None:
    project_id, reset = _parse_args()
    namespace = f"project_{project_id}"

    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index)

    if reset:
        try:
            index.delete(delete_all=True, namespace=namespace)
            print(f"Reset: deleted all vectors in namespace '{namespace}'.\n")
        except Exception as exc:  # noqa: BLE001 - namespace may not exist yet
            print(f"Reset: nothing to delete in '{namespace}' ({exc}).\n")

    stats = index.describe_index_stats()
    print(f"Index      : {settings.pinecone_index}")
    print(f"Dimension  : {stats.get('dimension')}")
    print(f"Namespaces : {list((stats.get('namespaces') or {}).keys())}")
    ns_stats = (stats.get("namespaces") or {}).get(namespace, {})
    print(f"Vectors in '{namespace}': {ns_stats.get('vector_count', 0)}")
    print("-" * 60)

    # Collect the IDs stored under this namespace.
    ids = []
    for page in index.list(namespace=namespace):
        ids.extend(page)
    if not ids:
        print(f"No vectors found in namespace '{namespace}'.")
        return

    # Fetch full records (values + metadata) for those IDs.
    fetched = index.fetch(ids=ids, namespace=namespace)
    vectors = fetched.vectors if hasattr(fetched, "vectors") else fetched["vectors"]

    for vid, rec in vectors.items():
        values = rec["values"] if isinstance(rec, dict) else rec.values
        meta = rec["metadata"] if isinstance(rec, dict) else rec.metadata
        preview = ", ".join(f"{v:.4f}" for v in values[:5])
        print(f"ID       : {vid}")
        print(f"Vector   : [{preview}, ...]  (dim={len(values)})")
        print(f"Metadata : {meta}")
        print("-" * 60)


if __name__ == "__main__":
    main()
