"""Generate openapi.yaml from the FastAPI app so the contract stays machine-readable.

Run through `tools.ps1 gen-api`. The file is committed; a non-empty diff in CI
means the routes drifted from the committed contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from fastapi.openapi.utils import get_openapi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


def build_spec() -> dict[str, Any]:
    return get_openapi(
        title=app.title,
        version=app.version,
        description="Research assistant agent API (01 §5).",
        routes=app.routes,
    )


def main() -> int:
    target = Path(__file__).resolve().parents[2] / "openapi.yaml"
    spec = build_spec()
    serialized = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, width=110)
    if target.exists() and target.read_text(encoding="utf-8") == serialized:
        print(f"openapi.yaml up to date ({len(spec.get('paths', {}))} paths)")
        return 0
    target.write_text(serialized, encoding="utf-8")
    print(f"wrote {target} ({len(spec.get('paths', {}))} paths)")
    print(json.dumps(sorted(spec.get("paths", {})), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
