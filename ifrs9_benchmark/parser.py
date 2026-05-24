from __future__ import annotations

import re
import os
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class PageBlock:
    page: int
    text: str
    score: int = 0


LOCATOR_TERMS = [
    "expected credit loss", "ecl", "ifrs 9", "impairment allowance",
    "loss allowance", "loans and advances", "gross carrying amount",
    "stage 1", "stage 2", "stage 3", "significant increase in credit risk",
    "sicr", "management adjustment", "judgemental adjustment", "overlay",
    "scenario", "probability weighted", "write-off", "maximum exposure",
    "credit risk", "trade receivables", "customer receivables",
    "macroeconomic", "scenario weighting", "probability weight", "upside",
    "downside", "baseline", "base case", "post model adjustment",
    "pma", "economic uncertainty", "30 days past due", "90 days past due",
    "past due", "watchlist", "forbearance", "pd", "lgd", "ead",
    "climate risk", "climate-related", "judgemental adjustment",
]


class PdfParser:
    def __init__(self, preference: str = "auto") -> None:
        self.preference = preference
        self.parser_used = "pymupdf"

    def parse(self, pdf_path: Path) -> list[PageBlock]:
        return self._parse_with_pymupdf(pdf_path)

    def _parse_with_pymupdf(self, pdf_path: Path) -> list[PageBlock]:
        blocks: list[PageBlock] = []
        with fitz.open(pdf_path) as doc:
            for index, page in enumerate(doc, start=1):
                text = self._extract_layout_text(page)
                initial_score = score_page(text)
                table_text = self._extract_tables(page) if os.environ.get("IFRS9_EXTRACT_TABLES") == "1" and initial_score >= 8 else ""
                combined = f"# Page {index}\n\n{text}\n\n{table_text}".strip()
                blocks.append(PageBlock(page=index, text=combined, score=score_page(combined)))
        return blocks

    def _extract_layout_text(self, page: fitz.Page) -> str:
        words = page.get_text("words")
        if not words:
            return page.get_text("text", sort=True)

        groups: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
        for word in words:
            x0, y0, _x1, _y1, text, block_no, line_no, *_ = word
            groups.setdefault((int(block_no), int(line_no)), []).append((float(x0), float(y0), str(text)))

        rendered_lines: list[tuple[float, str]] = []
        page_width = max(float(page.rect.width), 1.0)
        for (_block_no, _line_no), line_words in groups.items():
            line_words.sort(key=lambda item: item[0])
            y = min(item[1] for item in line_words)
            pieces: list[str] = []
            last_col = 0
            for x0, _y0, text in line_words:
                col = int((x0 / page_width) * 120)
                gap = max(1, min(col - last_col, 16))
                if pieces:
                    pieces.append(" " * gap)
                pieces.append(text)
                last_col = col + len(text)
            rendered_lines.append((y, "".join(pieces).rstrip()))

        rendered_lines.sort(key=lambda item: item[0])
        return "\n".join(line for _y, line in rendered_lines)

    def _extract_tables(self, page: fitz.Page) -> str:
        try:
            finder = page.find_tables()
        except Exception:
            return ""
        rendered: list[str] = []
        for table_index, table in enumerate(finder.tables, start=1):
            rows = table.extract()
            clean_rows = [["" if cell is None else str(cell).replace("\n", " ").strip() for cell in row] for row in rows]
            if not clean_rows:
                continue
            width = max(len(row) for row in clean_rows)
            clean_rows = [row + [""] * (width - len(row)) for row in clean_rows]
            header = clean_rows[0]
            rendered.append(f"Table {table_index}")
            rendered.append("| " + " | ".join(header) + " |")
            rendered.append("| " + " | ".join(["---"] * width) + " |")
            for row in clean_rows[1:]:
                rendered.append("| " + " | ".join(row) + " |")
        return "\n".join(rendered)


def score_page(text: str) -> int:
    lowered = text.lower()
    score = 0
    for term in LOCATOR_TERMS:
        if term in lowered:
            score += 4 if term in {"expected credit loss", "ifrs 9", "stage 1", "stage 2", "stage 3"} else 2
    score += min(len(re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", text)), 25)
    return score


def select_candidate_pages(blocks: list[PageBlock], max_pages: int) -> list[PageBlock]:
    chosen: dict[int, PageBlock] = {}
    priority_terms = [
        "maximum exposure to credit risk",
        "loans and advances to customers",
        "loans and advances at amortised cost by product",
        "movement in total exposures",
        "movement in gross exposures",
        "reconciliation of ecl movement",
        "credit impairment charge",
        "scenario weighting",
        "scenario weights",
        "macroeconomic scenarios",
        "management adjustments",
        "post model adjustments",
        "judgemental adjustments",
        "economic uncertainty adjustment",
        "climate risk ecl",
        "climate-related",
        "stage 2 decomposition",
        "significant increase in credit risk",
        "30 days past due",
        "90 days past due",
        "probability of default",
        "loss given default",
        "exposure at default",
    ]
    for block in blocks:
        lowered = block.text.lower()
        if any(term in lowered for term in priority_terms):
            chosen[block.page] = block
    for block in sorted(blocks, key=lambda item: item.score, reverse=True)[: max_pages // 2]:
        for page_number in (block.page - 1, block.page, block.page + 1):
            if 1 <= page_number <= len(blocks):
                chosen[page_number] = blocks[page_number - 1]
    return sorted(chosen.values(), key=lambda item: (_priority_score(item.text), item.score), reverse=True)[:max_pages]


def _priority_score(text: str) -> int:
    lowered = text.lower()
    terms = [
        "maximum exposure to credit risk",
        "loans and advances to customers",
        "loans and advances at amortised cost by product",
        "movement in total exposures",
        "movement in gross exposures",
        "reconciliation of ecl movement",
        "credit impairment charge",
        "scenario weighting",
        "scenario weights",
        "macroeconomic scenarios",
        "management adjustments",
        "post model adjustments",
        "judgemental adjustments",
        "economic uncertainty adjustment",
        "climate risk ecl",
        "climate-related",
        "stage 2 decomposition",
        "significant increase in credit risk",
        "30 days past due",
        "90 days past due",
        "probability of default",
        "loss given default",
        "exposure at default",
    ]
    return sum(1 for term in terms if term in lowered)
