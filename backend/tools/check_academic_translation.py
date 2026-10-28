"""Acceptance check for Chinese → English academic translation (T7.4).

Uses the live API and the real model. The sample is an original abstract that
contains the things an academic translator must not damage: a model name
(``Transformer``), an acronym (``RAG``), a metric (``BLEU``), a citation and
an inline formula.

Checks:

  * **A1** — the response is English (no CJK), has academic sentence lengths,
    and keeps every formula, citation and technical term;
  * **A2** — posting the same abstract again is served from the cache and is
    byte-identical.

Run from `backend/` with the API up:

    .venv/Scripts/python.exe -I tools/check_academic_translation.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

API = "http://127.0.0.1:8000/api/v1"
SAMPLE = (
    "近年来，检索增强生成（RAG）在开放域问答中取得显著进展，但检索噪声仍会误导生成模型。"
    "已有研究[12]表明，证据筛选能够降低幻觉风险。本文提出一种基于 Transformer 的双阶段过滤方法，"
    "先在块级估计相关性，再利用重排序器联合建模问题与证据。我们在三个公开数据集上进行实验，"
    "所提方法在 Exact Match 上平均提升 3.5 个百分点，在 BLEU 上提升 2.1，"
    "并在 $k=5$ 时保持稳定。消融实验表明，块级过滤贡献了主要收益，而重排序器对长尾问题尤为有效。"
    "上述结果说明，显式的证据筛选能够缓解检索噪声带来的幻觉风险。"
)
TERMS = ("RAG", "Transformer", "BLEU")
CJK = re.compile(r"[一-鿿]")


def sentence_stats(text: str) -> tuple[int, float]:
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    words = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    return len(sentences), words / max(1, len(sentences))


def check_translation(body: dict[str, object]) -> bool:
    text = str(body.get("text", "")).strip()
    ok = True
    if body.get("direction") != "zh2en":
        print(f"A1: FAIL — direction={body.get('direction')!r}")
        ok = False
    cjk = CJK.findall(text)
    if cjk:
        print(f"A1: FAIL — {len(cjk)} CJK characters in the translation: {''.join(cjk[:20])}")
        ok = False
    if "$k=5$" not in text:
        print("A1: FAIL — the inline formula $k=5$ was not kept byte for byte")
        ok = False
    if "[12]" not in text:
        print("A1: FAIL — the citation [12] was not kept")
        ok = False
    for term in TERMS:
        if term.lower() not in text.lower():
            print(f"A1: FAIL — technical term {term!r} is missing")
            ok = False
    count, average = sentence_stats(text)
    if count < 3 or not 8.0 <= average <= 45.0:
        print(f"A1: FAIL — {count} sentences, {average:.1f} words each; not academic prose")
        ok = False
    lowered = text.lower()
    if lowered.startswith(("translation", "english:", "sure,")) or "as an ai" in lowered:
        print("A1: FAIL — the model added a preamble instead of only the translation")
        ok = False
    print(f"  {len(text)} chars, {count} sentences, {average:.1f} words/sentence")
    print(f"  {text}")
    print(f"A1: {'PASS' if ok else 'FAIL'} — English academic register with formulas, citation and terms intact")
    return ok


async def main() -> int:
    payload = {"text": SAMPLE, "direction": "zh2en"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        started = time.monotonic()
        response = await client.post(f"{API}/translate/zh2en", json=payload)
        elapsed = (time.monotonic() - started) * 1000
        if response.status_code != 200:
            print(f"A1: FAIL — HTTP {response.status_code}: {response.text[:300]}")
            return 1
        first = response.json()
        print(f"  first call {elapsed:.0f} ms, cached={first.get('cached')}")
        ok = check_translation(first)
        if first.get("cached") is not False:
            print("A1: FAIL — the first call should not be cached")
            ok = False

        second = (await client.post(f"{API}/translate/zh2en", json=payload)).json()
        cache_ok = second.get("cached") is True and second.get("text") == first.get("text")
        print(f"A2: {'PASS' if cache_ok else 'FAIL'} — the identical second call is cached and byte-identical")
        ok = ok and cache_ok
    print(f"academic translation: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
