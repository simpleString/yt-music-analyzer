import re

_SUFFIXES = [
    r"[-–—]\s*topic",
    r"[-–—]?\s*vevo",
    r"[-–—]\s*official\s+artist\s+channel",
    r"[-–—]\s*official",
    r"\(\s*official\s*\)",
]

_MULTISPACE = re.compile(r"\s{2,}")
_COMPILED = [(re.compile(p + r"\s*$", re.IGNORECASE), "") for p in _SUFFIXES]


def normalize_artist(channel: str | None) -> str:
    """Canonical artist name derived from the channel title.

    Strips common trailing suffixes ("- Topic", "VEVO", "- Official",
    etc.) and collapses extra whitespace. Case is preserved as-is.
    """
    name = (channel or "").strip()
    for rx, repl in _COMPILED:
        name = rx.sub(repl, name).rstrip()
    name = _MULTISPACE.sub(" ", name).strip(" -–—\t")
    return name.strip()
