"""One-off: create the Book Forge Pinecone index if it doesn't exist.

Reads key / index name / cloud / region from your .env (via settings), so no
secrets are hard-coded. Run once from the repo root with the venv active:

    python scripts/create_pinecone_index.py

Dimension 1536 matches text-embedding-3-small; metric cosine.
"""
import sys
from pathlib import Path

# Make the repo root importable when run as `python scripts/create_pinecone_index.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pinecone import Pinecone, ServerlessSpec

from src.core.config import settings

DIMENSION = 1536  # text-embedding-3-small
METRIC = "cosine"


def main() -> None:
    name = settings.pinecone_index
    pc = Pinecone(api_key=settings.pinecone_api_key)

    existing = pc.list_indexes().names()
    if name in existing:
        print(f"Index '{name}' already exists — nothing to do.")
        return

    print(
        f"Creating index '{name}' (dim={DIMENSION}, metric={METRIC}, "
        f"cloud={settings.pinecone_cloud}, region={settings.pinecone_region})..."
    )
    pc.create_index(
        name=name,
        dimension=DIMENSION,
        metric=METRIC,
        spec=ServerlessSpec(
            cloud=settings.pinecone_cloud, region=settings.pinecone_region
        ),
    )
    print(f"Created '{name}'. It may take a few seconds to become ready.")


if __name__ == "__main__":
    main()
