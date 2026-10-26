"""Manual check: parse the fixture PDFs and print the anchored metadata.

Usage: python -m scripts.check_meta [--no-llm] [pdf ...]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.ingest import pdfio
from app.ingest.metadata import extract_meta_llm, rule_based_meta
from app.ingest.parser import extract_blocks, probe_pages
from app.llm.gateway import get_gateway, set_gateway

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"


async def run(path: Path, use_llm: bool) -> None:
    settings = get_settings()
    doc = pdfio.open_document(path)
    try:
        pages = probe_pages(doc, settings.scanned_page_char_threshold)
        blocks, _ = extract_blocks(doc, pages, "doc-check", page_limit=1)
        if use_llm:
            meta = await extract_meta_llm(doc, blocks, "doc-check", get_gateway())
        else:
            meta = rule_based_meta(doc, blocks, "doc-check")
    finally:
        pdfio.close_document(doc)
    print(f"\n=== {path.name} ===")
    print(meta.model_dump_json(indent=2))


async def main_async(paths: list[Path], use_llm: bool) -> None:
    try:
        for path in paths:
            await run(path, use_llm)
    finally:
        await get_gateway().close()
        set_gateway(None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("pdf", nargs="*")
    args = parser.parse_args()

    paths = [Path(p) for p in args.pdf] or sorted(FIXTURES.glob("*.pdf"))
    if not paths:
        print(f"no PDFs in {FIXTURES}", file=sys.stderr)
        return 1
    # One loop for the whole run: the gateway's HTTP/Redis clients bind to it.
    asyncio.run(main_async(paths, not args.no_llm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
