from pathlib import Path


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def split_words(text: str) -> list[str]:
    return [w for w in text.replace("\n", " ").split(" ") if w]
