"""CLI runner: execute all source adapters (or a subset via --source)."""
import argparse
import importlib

from scrapers.core import pipeline

SOURCES = ["sauto", "autodraft", "energycars"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", choices=SOURCES,
                    help="run only these sources (default: all)")
    args = ap.parse_args()
    targets = args.source or SOURCES
    for name in targets:
        mod = importlib.import_module(f"scrapers.sources.{name}")
        print(f"=== {mod.SOURCE_NAME} ===")
        pipeline.run_source(mod)


if __name__ == "__main__":
    main()
