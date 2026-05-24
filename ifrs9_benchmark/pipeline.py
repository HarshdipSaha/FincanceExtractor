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
        max_pages_per_pdf: int = 36,
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


def build_llm_context(pages, max_chars: int = 16000) -> str:
    terms = [
        "expected credit loss", "ecl", "ifrs 9", "stage 1", "stage 2", "stage 3",
        "loans and advances", "maximum exposure", "loss allowance",
        "impairment allowance", "gross carrying amount", "trade receivables",
        "significant increase in credit risk", "management adjustment",
        "judgemental adjustment", "overlay", "scenario", "write-off",
        "climate", "30 days past due", "90 days past due",
        "macroeconomic", "scenario weighting", "scenario weights",
        "probability weight", "upside", "downside", "baseline", "base case",
        "post model adjustment", "pma", "economic uncertainty",
        "watchlist", "forbearance", "probability of default",
        "loss given default", "exposure at default", "pd", "lgd", "ead",
        "credit impairment charge", "reconciliation of ecl movement",
    ]
    chunks: list[str] = []
    for page in pages:
        text = page.text.replace("\x00", " ")
        lowered = text.lower()
        spans: list[tuple[int, int]] = []
        for term in terms:
            start = lowered.find(term)
            if start >= 0:
                spans.append((max(0, start - 1200), min(len(text), start + 2600)))
        if not spans:
            spans.append((0, min(len(text), 1400)))
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + 300:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        page_chunks = [text[start:end] for start, end in merged[:2]]
        chunks.append(f"# Page {page.page}\n" + "\n...\n".join(page_chunks))
        if sum(len(chunk) for chunk in chunks) > max_chars:
            break
    return "\n\n".join(chunks)[:max_chars]
