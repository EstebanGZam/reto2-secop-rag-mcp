"""Build the local tender index: uv run python scripts/build_index.py [--rebuild]."""
from __future__ import annotations

import argparse

from secop_agent.rag import build_index, load_corpus


def main() -> None:
    """Parse CLI options and report indexed document and chunk counts."""
    parser = argparse.ArgumentParser(description="Build the persistent tender PDF index")
    parser.add_argument("--rebuild", action="store_true", help="Delete the collection before indexing")
    args = parser.parse_args()
    chunks = load_corpus()
    count = build_index(chunks, rebuild=args.rebuild)
    print(f"Indexed {len({chunk.source_file for chunk in chunks})} documents; {count} chunks")


if __name__ == "__main__":
    main()
