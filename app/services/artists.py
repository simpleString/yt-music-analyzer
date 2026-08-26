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
    """Каноническое имя исполнителя из названия канала.

    Убирает типовые суффиксы в конце ("- Topic", "VEVO", "- Official" и т.п.),
    схлопывает лишние пробелы. Регистр сохраняется как в оригинале.
    """
    name = (channel or "").strip()
    for rx, repl in _COMPILED:
        name = rx.sub(repl, name).rstrip()
    name = _MULTISPACE.sub(" ", name).strip(" -–—\t")
    return name.strip()
