"""Prompts and cache identity for block translation (T4.1/T4.2/T4.4).

Keeping the prompt text, the direction table and the cache-key formula in one
module makes the versioned identity easy to audit: changing the prompt must
change `PROMPT_VERSION`, and the glossary version/fingerprint is part of the
same key. `service.py` re-exports `cache_key` for compatibility with callers
that imported it from there.
"""

from __future__ import annotations

import hashlib

from ..llm.safety import wrap_data
from .glossary import Glossary

PROMPT_VERSION = "v1"

_SYSTEM = (
    "Translate research-paper text from {src} into {dst}. "
    "Keep every number, term and placeholder (⟦0⟧) exactly as written, once each. "
    "Output only the translation."
)
_DIRECTION = {
    "en2zh": ("English", "Simplified Chinese"),
    "zh2en": ("Simplified Chinese", "academic English"),
}


def messages(text: str, direction: str, system: str | None = None) -> list[dict[str, str]]:
    src, dst = _DIRECTION[direction]
    prompt = system or _SYSTEM.format(src=src, dst=dst)
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"Translate the text between the markers.\n{wrap_data(text)}",
        },
    ]


def cache_key(text: str, direction: str, glossary_version: int = 0, glossary_fingerprint: str = "") -> str:
    """Block identity in the translation cache (01 §6).

    Version 0 keeps the unprefixed v1 form so rows written before the glossary
    existed stay valid; once a reader has a list, every edit bumps the version
    and the key changes, which is what forces a retranslation with the new
    terms. The content fingerprint is part of the key because the rows are
    shared by document while versions are per user: two readers at version 1
    with different lists must not collide.
    """
    payload = (
        f"{PROMPT_VERSION}|{direction}|g{glossary_version}|{glossary_fingerprint}|{text}"
        if glossary_version or glossary_fingerprint
        else f"{PROMPT_VERSION}|{direction}|{text}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def system_for(
    direction: str,
    text: str,
    glossary: Glossary | None,
    system: str | None = None,
) -> str:
    src, dst = _DIRECTION[direction]
    prompt = system or _SYSTEM.format(src=src, dst=dst)
    if glossary is not None:
        prompt += glossary.prompt_suffix(text)
    return prompt
