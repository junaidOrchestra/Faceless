"""Detect verbal filler / hesitation words ("um", "uh", "hmm", "aaah", …).

Used by the transcriber to flag words so the editor can offer "remove filler
words". We deliberately keep this CONSERVATIVE: only unambiguous hesitation
sounds are flagged, never real words like "like", "so" or "well" (which are
filler only in context and removing them blindly would mangle the narration).

Note: Whisper is trained to clean up speech and often omits fillers entirely, so
this catches the ones that survive transcription rather than every disfluency.
"""

from __future__ import annotations

import re

# Exact hesitation tokens (after normalization to lowercase, no punctuation).
_FILLER_WORDS: frozenset[str] = frozenset(
    {
        "um", "umm", "ummm",
        "uh", "uhh", "uhhh",
        "uhm", "uhmm",
        "hmm", "hm", "hmmm",
        "mm", "mmm", "mmmm",
        "mhm", "mhmm",
        "er", "err", "erm", "errm",
        "ah", "ahh", "aah", "aaah",
        "eh", "ehh",
    }
)

# Elongated variants ("uuummm", "ahhh"). Anchored to the WHOLE token so it can
# never match inside a real word, and each alternative needs the consonant that
# makes it a hesitation (so a bare "a" or "e" is never flagged).
_FILLER_RE = re.compile(
    r"^(?:u+m+|u+h+m*|h+m+|m{2,}|e+r+m*|a+h+|e+h+)$",
    re.IGNORECASE,
)

# Strip surrounding punctuation/space; keep inner letters and hyphens.
_STRIP_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def normalize(token: str) -> str:
    """Lowercase a word token and strip leading/trailing punctuation/space."""

    return _STRIP_RE.sub("", token).lower()


def is_filler(token: str) -> bool:
    """True if ``token`` is an unambiguous verbal filler / hesitation."""

    word = normalize(token)
    if not word:
        return False
    if word in _FILLER_WORDS:
        return True
    return bool(_FILLER_RE.match(word))
