"""What a caller says before they are verified is kept masked in the transcript and on the live stream. The details
given to verify_identity (an account number, a postcode, a date of birth) are numbers, codes and dates, so the runs of
them are replaced by "[masked]". Ordinary words are left as they are.

The agent itself is given the words as said (its context is not masked), and the verification event records only the
result. Once the caller is verified, the transcript shows what was said.
"""

import re

from app.agent.tools import DIGITS, MONTHS, ORDINALS, SMALL, TENS

MASK = "[masked]"
NUMBER_WORDS = set(DIGITS) | set(SMALL) | set(TENS) | set(ORDINALS) | {"thousand", "hundred", "double", "triple"}
CONNECTORS = {"of", "the", "and", "st", "nd", "rd", "th"}


def _core(word: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", word)


def _sensitive(word: str) -> bool:
    core = _core(word)
    if not core:
        return False
    if any(c.isdigit() for c in core):  # account numbers, postcodes, days and years
        return True
    low = core.lower()
    if low in MONTHS or low in NUMBER_WORDS:  # spoken dates and spelled digits
        return True
    return core.isupper() and len(core) <= 2  # spelled letters of a code: "N G", "A B"


def _masks(run: list[str]) -> bool:
    """A run is masked when it holds a number, a date, or a spelled-out code of several words."""
    cores = [_core(w) for w in run]
    if any(c.isdigit() for core in cores for c in core):
        return True
    if any(c.lower() in MONTHS for c in cores):
        return True
    return sum(c.lower() in NUMBER_WORDS for c in cores) >= 2 and len(run) >= 4


def mask_identifiers(said: str) -> str:
    words = said.split()
    flags = [_sensitive(w) or _core(w).lower() in CONNECTORS for w in words]
    out, i = [], 0
    while i < len(words):
        if not flags[i]:
            out.append(words[i])
            i += 1
            continue
        j = i
        while j < len(words) and flags[j]:
            j += 1
        a, b = i, j  # connectors at the ends of a run are not part of it ("the 25th" keeps "the")
        while a < b and _core(words[a]).lower() in CONNECTORS:
            a += 1
        while b > a and _core(words[b - 1]).lower() in CONNECTORS:
            b -= 1
        if a < b and _masks(words[a:b]):
            trailing = re.search(r"[^\w]*$", words[b - 1]).group()
            out.extend(words[i:a])
            out.append(MASK + trailing)
            out.extend(words[b:j])
        else:
            out.extend(words[i:j])
        i = j
    return " ".join(out)
