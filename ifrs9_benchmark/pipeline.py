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


def build_llm_context(pages, max_chars: int = 150000) -> str:
    # Sort pages by page number so the LLM reads them in natural document order
    sorted_pages = sorted(pages, key=lambda p: p.page)
    
    chunks: list[str] = []
    current_length = 0
    
    for page in sorted_pages:
        text = page.text.replace("\x00", " ")
        page_chunk = f"# Page {page.page}\n{text}\n"
        
        if current_length + len(page_chunk) > max_chars:
            # If adding the whole page exceeds max_chars, truncate this page and stop
            allowed = max_chars - current_length
            if allowed > 100:
                chunks.append(page_chunk[:allowed] + "\n...[TRUNCATED]")
            break
            
        chunks.append(page_chunk)
        current_length += len(page_chunk)
        
    return "\n".join(chunks)
