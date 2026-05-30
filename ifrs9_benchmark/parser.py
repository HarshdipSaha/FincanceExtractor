from __future__ import annotations

import re
import os
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

@dataclass
class PageBlock:
    page: int
    text: str
    score: int = 0


# ONTOLOGY MAP FOR DISCLOSURES
ONTOLOGY = {
    "gross_exposure": ["gross receivables", "gross carrying amount", "gross exposure", "loans and advances", "customer loans", "trade receivables"],
    "ecl_allowance": ["ecl allowance", "impairment allowance", "loss allowance", "provision"],
    "net_exposure": ["net receivables", "net exposure", "carrying amount"],
    "staging": ["stage 1", "stage 2", "stage 3", "credit-impaired", "defaulted", "poci"],
    "impairment_movement": ["impairment movement", "credit impairment charge", "release", "write-offs", "charge-offs", "reconciliation of allowance", "movement in allowance", "allowance for expected credit losses", "reconciliation of ecl", "movement in expected credit loss"],
    "management_adjustment": ["management adjustment", "pma", "overlay", "judgemental adjustment", "economic uncertainty", "post model adjustment", "post-model adjustment"],
    "scenarios": ["scenario", "upside", "base case", "baseline", "downside", "stress scenario", "macroeconomic", "multiple economic scenarios", "mes", "economic variables", "scenario weights"],
    "sicr": ["sicr", "significant increase in credit risk", "30 days past due", "90 days past due", "watchlist", "forbearance"],
    "model_design": ["framework", "methodology", "probability of default", "loss given default", "exposure at default", "pd", "lgd", "ead", "backstop", "climate risk"],
    "priority_tables": [
        "maximum exposure to credit risk",
        "loans and advances to customers",
        "movement in total exposures",
        "movement in gross exposures",
        "reconciliation of ecl movement",
        "reconciliation of allowance",
        "movement in allowance",
        "credit impairment charge",
        "macroeconomic scenarios",
        "economic uncertainty"
    ]
}

# Flatten ontology terms for page filtering
ALL_TERMS = set()
for terms in ONTOLOGY.values():
    for term in terms:
        ALL_TERMS.add(term.lower())


class PdfParser:
    def __init__(self, preference: str = "auto") -> None:
        self.preference = preference
        self.parser_used = "pdfplumber"

    def parse(self, pdf_path: Path) -> list[PageBlock]:
        try:
            blocks: list[PageBlock] = []
            with pdfplumber.open(pdf_path) as pdf:
                for index, page in enumerate(pdf.pages, start=1):
                    # extract_text(layout=True) attempts to keep visual structure (spaces, tables)
                    text = page.extract_text(layout=True) or ""
                    
                    # If layout extraction fails to yield much, fallback to normal
                    if len(text.strip()) < 50:
                        text = page.extract_text() or ""
                        
                    combined = f"# Page {index}\n\n{text}".strip()
                    score = self.score_page(combined)
                    blocks.append(PageBlock(page=index, text=combined, score=score))
            return blocks
        except Exception as e:
            print(f"Error parsing with pdfplumber: {e}")
            return []

    def score_page(self, text: str) -> int:
        lowered = text.lower()
        score = 0
        for term in ALL_TERMS:
            if term in lowered:
                score += 4 if term in ["expected credit loss", "ifrs 9", "stage 1", "stage 2", "stage 3"] else 2
        # Score numeric density loosely
        score += min(len(re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", text)), 25)
        return score


def select_candidate_pages(blocks: list[PageBlock], max_pages: int) -> list[PageBlock]:
    chosen: dict[int, PageBlock] = {}
    
    # Identify pages with strict priority terms
    priority_terms = ONTOLOGY["priority_tables"]
    
    for block in blocks:
        lowered = block.text.lower()
        if any(term in lowered for term in priority_terms):
            chosen[block.page] = block

    # Include adjacent pages for priority pages
    priority_pages = list(chosen.keys())
    for page_num in priority_pages:
        for adj in (page_num - 1, page_num + 1):
            if adj > 0 and adj not in chosen:
                # Find block by page number
                adj_block = next((b for b in blocks if b.page == adj), None)
                if adj_block:
                    chosen[adj] = adj_block

    # Include pages with score >= 4
    for block in blocks:
        if block.score >= 4 and block.page not in chosen:
            chosen[block.page] = block

    # Fill remainder up to max_pages based on score
    if len(chosen) < max_pages:
        remaining = sorted(
            [b for b in blocks if b.page not in chosen],
            key=lambda item: item.score, reverse=True
        )
        for block in remaining:
            if len(chosen) >= max_pages:
                break
            chosen[block.page] = block

    return sorted(chosen.values(), key=lambda item: item.page)

