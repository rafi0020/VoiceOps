"""What is spoken is not exactly what is written: citations stay in the transcript but are not read aloud, and the
reply is split into sentences so the first can be synthesised and played while the rest are prepared."""

import re

CITATION = re.compile(r"\s*\[[\w-]+ §[\w.]+\]")


def speakable(text: str) -> str:
    return re.sub(r"\s+", " ", CITATION.sub("", text)).strip()


def sentences(text: str, min_chars: int = 25) -> list[str]:
    """Sentences to synthesise one by one; very short ones ride with the next so the voice does not stutter."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", speakable(text)) if p.strip()]
    out: list[str] = []
    for part in parts:
        if out and len(out[-1]) < min_chars:
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out
