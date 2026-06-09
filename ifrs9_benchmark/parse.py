from __future__ import annotations

import io
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .fetch import HttpClient
from .models import PageData, SourceDocument, TableData
from .utils import normalize_space

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency at runtime only
    PdfReader = None


NUMBER_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
CELL_SPLIT_RE = re.compile(r"\s{2,}|\t+")
TABULAR_KEYWORDS = (
    "stage",
    "gross",
    "net",
    "ecl",
    "allowance",
    "impairment",
    "coverage",
    "exposure",
    "write-off",
    "write off",
    "charge",
    "opening",
    "closing",
    "past due",
    "delinquen",
)


def _line_to_row(line: str) -> list[str] | None:
    numbers = NUMBER_RE.findall(line)
    if not numbers:
        return None
    first_number = NUMBER_RE.search(line)
    if not first_number:
        return None
    label = normalize_space(line[: first_number.start()])
    if not label:
        return None
    return [label] + numbers[:5]


def _extract_page_text(page) -> str:
    try:
        text = page.extract_text(extraction_mode="layout")
    except TypeError:
        text = page.extract_text()
    return text or ""


def _normalize_pdf_page_text(text: str) -> str:
    lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    return "\n".join(lines)


def _split_layout_cells(line: str) -> list[str]:
    return [normalize_space(part) for part in CELL_SPLIT_RE.split(line.rstrip()) if normalize_space(part)]


def _looks_tabular_row(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    label = cells[0].lower()
    numeric_cells = 0
    special_cells = 0
    for cell in cells[1:]:
        if NUMBER_RE.fullmatch(cell.replace("%", "")):
            numeric_cells += 1
        elif cell.strip().lower() in {"-", "na", "nm", "n/a"}:
            special_cells += 1
    if numeric_cells >= 2:
        return True
    if numeric_cells >= 1 and any(keyword in label for keyword in TABULAR_KEYWORDS):
        return True
    if numeric_cells == 0 and special_cells >= 2 and any(keyword in label for keyword in TABULAR_KEYWORDS):
        return True
    return False


def _table_block_to_data(rows: list[list[str]], source_url: str, page_index: int, block_index: int) -> TableData | None:
    meaningful_rows = [row for row in rows if row]
    if len(meaningful_rows) < 3:
        return None
    max_cols = max(len(row) for row in meaningful_rows)
    columns = ["Row"] + [f"Value {idx}" for idx in range(1, max_cols)]
    padded_rows = [row + [""] * (max_cols - len(row)) for row in meaningful_rows]
    return TableData(
        title=f"PDF extracted table page {page_index}.{block_index}",
        columns=columns,
        rows=padded_rows,
        source_url=source_url,
        location=f"page-{page_index}",
    )


def _extract_pdf_layout_tables(page_text: str, source_url: str, page_index: int) -> list[TableData]:
    raw_lines = [line.rstrip() for line in page_text.splitlines() if line.strip()]
    blocks: list[list[list[str]]] = []
    current_block: list[list[str]] = []
    last_candidate_line = -99

    for line_index, line in enumerate(raw_lines):
        cells = _split_layout_cells(line)
        if _looks_tabular_row(cells):
            if current_block and line_index - last_candidate_line > 2:
                blocks.append(current_block)
                current_block = []
            current_block.append(cells)
            last_candidate_line = line_index
            continue
        if current_block and line_index - last_candidate_line > 2:
            blocks.append(current_block)
            current_block = []
    if current_block:
        blocks.append(current_block)

    tables: list[TableData] = []
    for block_index, block in enumerate(blocks, start=1):
        table = _table_block_to_data(block, source_url, page_index, block_index)
        if table is not None:
            tables.append(table)
    return tables


def guess_document_type(url: str, content_hint: str | None = None) -> str:
    low = (url or "").lower()
    if low.endswith(".pdf") or ".pdf?" in low:
        return "pdf"
    if content_hint and "pdf" in content_hint.lower():
        return "pdf"
    return "html"


def html_tables(soup: BeautifulSoup, source_url: str) -> list[TableData]:
    parsed: list[TableData] = []
    for index, table_tag in enumerate(soup.find_all("table"), start=1):
        rows = table_tag.find_all("tr")
        matrix: list[list[str]] = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            matrix.append([normalize_space(cell.get_text(" ", strip=True)) for cell in cells])
        matrix = [row for row in matrix if any(cell for cell in row)]
        if not matrix:
            continue
        columns = matrix[0]
        body = matrix[1:] if len(matrix) > 1 else []
        title = f"HTML table {index}"
        parsed.append(TableData(title=title, columns=columns, rows=body, source_url=source_url, location=f"table-{index}"))
    return parsed


def parse_html_document(url: str, html: str) -> SourceDocument:
    soup = BeautifulSoup(html, "html.parser")
    text = normalize_space(soup.get_text("\n", strip=True))
    page = PageData(page_number=1, text=text, source_url=url, tables=html_tables(soup, url))
    return SourceDocument(
        url=url,
        document_type="html",
        text=text,
        pages=[page],
        tables=list(page.tables),
    )


def parse_pdf_document(url: str, payload: bytes, max_pages: int = 250) -> SourceDocument:
    if PdfReader is None:
        raise RuntimeError("pypdf is not installed. Install dependencies from requirements.txt")

    reader = PdfReader(io.BytesIO(payload))
    chunks: list[str] = []
    pages: list[PageData] = []
    tables: list[TableData] = []
    for page_index, page in enumerate(reader.pages, start=1):
        if page_index > max_pages:
            break
        text = _extract_page_text(page)
        if text.strip():
            normalized = _normalize_pdf_page_text(text)
            page_tables = _extract_pdf_layout_tables(text, url, page_index)
            chunks.append(f"[Page {page_index}]\n{normalized}")
            tables.extend(page_tables)
            pages.append(PageData(page_number=page_index, text=normalized, source_url=url, tables=page_tables))
    merged = "\n\n".join(chunks)
    return SourceDocument(url=url, document_type="pdf", text=merged, pages=pages, tables=tables)


def load_document(client: HttpClient, url: str, max_pdf_pages: int = 250) -> SourceDocument:
    doc_type = guess_document_type(url)
    if doc_type == "pdf":
        raw = client.get_bytes(url)
        return parse_pdf_document(url, raw, max_pages=max_pdf_pages)
    html = client.get_text(url)
    return parse_html_document(url, html)


def report_period_from_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    bits = path.split("/")
    year = None
    kind = None
    for bit in bits:
        if bit.isdigit() and len(bit) == 4:
            year = bit
        if bit in {"annual-report", "half-year-report", "quarterly-report", "interim-report"}:
            kind = bit
    if year and kind:
        return f"{kind} {year}"
    if year:
        return year
    fallback = re.search(r"(20\d{2})", url)
    if fallback:
        return fallback.group(1)
    return None
