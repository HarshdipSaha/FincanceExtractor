from __future__ import annotations

import re


PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
NUMBER_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    rough = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [normalize_space(s) for s in rough if normalize_space(s)]


def contains_all(text: str, terms: list[str]) -> bool:
    low = (text or "").lower()
    return all(term.lower() in low for term in terms)


def contains_any(text: str, terms: list[str]) -> bool:
    low = (text or "").lower()
    return any(term.lower() in low for term in terms)


def parse_number(raw: str | None) -> float | None:
    if not raw:
        return None
    token = normalize_space(raw)
    if not token:
        return None
    negative = token.startswith("(") and token.endswith(")")
    token = token.replace(",", "").replace("(", "").replace(")", "")
    try:
        value = float(token)
    except ValueError:
        return None
    return -value if negative else value


def first_number(text: str) -> float | None:
    m = NUMBER_RE.search(text or "")
    if not m:
        return None
    return parse_number(m.group(0))


def fmt_number(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(value)


def fmt_percent(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    fmt = f"{{:.{decimals}f}}%"
    return fmt.format(value * 100)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def best_sentences(text: str, keywords: list[str], limit: int = 3) -> list[str]:
    lines = split_sentences(text)
    scored: list[tuple[int, str]] = []
    for line in lines:
        low = line.lower()
        score = sum(1 for kw in keywords if kw in low)
        if score > 0:
            scored.append((score, line))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]
