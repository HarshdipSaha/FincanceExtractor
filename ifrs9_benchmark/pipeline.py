from __future__ import annotations

from pathlib import Path

from .config import load_local_keys
from .llm import GroqExtractor
from .models import BenchmarkReport, FirmReport
from .parser import PdfParser, select_candidate_pages
from .reporting import render_outputs
from .validator import validate_citations


class BenchmarkPipeline:
    def __init__(
        self,
        output_dir: Path,
        parser_preference: str = "auto",
        llm_model: str = "llama-3.3-70b-versatile",
        max_pages_per_pdf: int = 80,
    ) -> None:
        self.output_dir = output_dir
        self.parser = PdfParser(parser_preference)
        self.extractor = GroqExtractor(llm_model)
        self.max_pages_per_pdf = max_pages_per_pdf
        load_local_keys(Path.cwd())

    def run(self, pdf_paths: list[Path]) -> dict:
        firms: list[FirmReport] = []
        failures: list[dict[str, str]] = []
        for pdf_path in pdf_paths:
            try:
                all_pages = self.parser.parse(pdf_path)
                candidates = select_candidate_pages(all_pages, self.max_pages_per_pdf)
                context = build_llm_context(candidates)
                extracted_firms = self.extractor.extract(pdf_path.name, context)
                for firm_report in extracted_firms:
                    firm_report.parser_used = self.parser.parser_used
                    firm_report.source_pdf = pdf_path.name
                    firm_report = validate_citations(firm_report, candidates)
                    firms.append(firm_report)
            except Exception as exc:
                failures.append({"pdf": pdf_path.name, "error": str(exc)})
                firms.append(
                    FirmReport(
                        firm_name=pdf_path.stem,
                        source_pdf=pdf_path.name,
                        parser_used=self.parser.parser_used,
                        extraction_warnings=[f"Extraction failed for this PDF: {exc}"],
                    )
                )

        report = BenchmarkReport(firms=firms)
        outputs = render_outputs(report, self.output_dir)
        return {
            "outputs": outputs,
            "summary": {
                "firm_count": len(firms),
                "firms": [firm.firm_name for firm in firms],
                "warnings": sum(len(firm.extraction_warnings) for firm in firms),
                "failures": failures,
            },
        }


def build_llm_context(pages, max_chars: int = 28000) -> str:
    """Build LLM context from selected pages.
    
    Pages arrive already sorted by page number from select_candidate_pages.
    We include full text of each page until we approach max_chars, then
    switch to keyword-snippet mode for remaining pages to still capture
    model-design paragraphs without blowing token budgets.
    """
    sorted_pages = sorted(pages, key=lambda p: p.page)
    
    # Phase 1: Include full text of the highest-priority pages first
    full_text_chunks: list[str] = []
    snippet_pages: list = []
    current_length = 0
    
    for page in sorted_pages:
        text = page.text.replace("\x00", " ")
        page_chunk = f"# Page {page.page}\n{text}\n"
        
        if current_length + len(page_chunk) <= max_chars * 0.8:
            full_text_chunks.append(page_chunk)
            current_length += len(page_chunk)
        else:
            snippet_pages.append(page)
    
    # Phase 2: For remaining pages, extract keyword-targeted snippets
    snippet_terms = [
        "expected credit loss", "ecl", "ifrs 9", "stage 1", "stage 2", "stage 3",
        "loss allowance", "gross carrying amount", "significant increase in credit risk",
        "management adjustment", "judgemental adjustment", "overlay", "scenario",
        "climate", "macroeconomic", "scenario weighting", "scenario weights",
        "probability weight", "upside", "downside", "baseline", "base case",
        "post model adjustment", "pma", "economic uncertainty",
        "probability of default", "loss given default", "exposure at default",
        "backstop", "write-off", "credit impairment", "model building block",
        "sicr", "30 days past due", "90 days past due",
    ]
    
    for page in snippet_pages:
        if current_length >= max_chars:
            break
        text = page.text.replace("\x00", " ")
        lowered = text.lower()
        spans: list[tuple[int, int]] = []
        for term in snippet_terms:
            idx = 0
            while True:
                pos = lowered.find(term, idx)
                if pos < 0:
                    break
                spans.append((max(0, pos - 600), min(len(text), pos + 1200)))
                idx = pos + len(term)
        if not spans:
            continue
        # Merge overlapping spans
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + 200:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        snippets = [text[s:e] for s, e in merged]
        page_chunk = f"# Page {page.page} (snippets)\n" + "\n...\n".join(snippets) + "\n"
        
        if current_length + len(page_chunk) > max_chars:
            allowed = max_chars - current_length
            if allowed > 200:
                full_text_chunks.append(page_chunk[:allowed] + "\n...[TRUNCATED]")
                current_length += allowed
            break
        
        full_text_chunks.append(page_chunk)
        current_length += len(page_chunk)
    
    return "\n".join(full_text_chunks)
