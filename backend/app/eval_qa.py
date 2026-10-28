"""Run the golden-set QA evaluation and write its report (T3.6).

`tools/check_qa.py` is the real-model acceptance run. This module executes
that same script, echoes its progress, and hands the output to
``app.eval_report`` for metric parsing and rendering. It never invents a
metric: a missing line fails the run (H02/H05), and the report omits generated
answer text (H13).

Run from the repository root through either entry point:

    make eval-qa
    .\\tools.ps1 eval-qa

or directly from ``backend/``:

    .venv/Scripts/python.exe -m app.eval_qa
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from pathlib import Path

from app.eval_report import DEFAULT_OUTPUT, build_report, write_report

BACKEND = Path(__file__).resolve().parent.parent


def run_check(mode: str = "all", timeout: float = 3600.0) -> tuple[int, str]:
    """Run the real acceptance script, echo it, and return (exit code, output)."""
    command = [sys.executable, "-I", str(BACKEND / "tools" / "check_qa.py")]
    if mode != "all":
        command.append(mode)
    process = subprocess.Popen(
        command,
        cwd=BACKEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: list[str] = []

    def pump() -> None:
        stream = process.stdout
        if stream is None:
            return
        for line in stream:
            print(line, end="", flush=True)
            lines.append(line)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait()
        lines.append(f"\neval-qa: check timed out after {timeout:.0f}s\n")
    reader.join()
    return code, "".join(lines)


def _models() -> dict[str, str]:
    from app.config import get_settings

    settings = get_settings()
    return {
        "fast": settings.llm_fast,
        "strong": settings.llm_strong,
        "embed": settings.embed_model,
        "rerank": settings.rerank_model,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the golden QA set and write docs/eval-qa.*")
    parser.add_argument("--mode", choices=("all", "qa", "compare"), default="all")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    command = f"python -I tools/check_qa.py {args.mode}"
    print(f"eval-qa: running `{command}` (timeout {args.timeout:.0f}s)", flush=True)
    code, output = run_check(args.mode, args.timeout)
    if code != 0:
        print(f"eval-qa: check_qa exited {code}", file=sys.stderr)
    try:
        report = build_report(output, command=command, models=_models())
    except ValueError as error:
        print(f"eval-qa: FAIL — {error}", file=sys.stderr)
        return 1

    json_path, markdown_path = write_report(report, args.output_dir)
    print(f"eval-qa: {report.verdict} — {json_path} / {markdown_path}")
    if report.verdict != "PASS" or code != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
