from __future__ import annotations

from pathlib import Path

from rank_bm25 import BM25Okapi

from .config import load_local_keys
from .llm import GroqExtractor
from .models import BenchmarkReport, FirmReport
from .parser import PdfParser, select_candidate_pages, ONTOLOGY
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


def build_llm_context(pages, max_chars: int = 80000) -> str:
    """Build LLM context using Chunking + BM25 RAG.
    
    Splits the parsed Markdown into chunks, then retrieves the most 
    relevant chunks based on the Ontology map.
    """
    if not pages:
        return ""

    # 1. Chunk pages into smaller blocks (e.g. split by markdown headers or double newlines)
    chunks = []
    for page in pages:
        # In markdown from pymupdf4llm, paragraphs and tables are separated by \n\n
        paragraphs = page.text.split("\n\n")
        current_chunk = ""
        for p in paragraphs:
            # Chunk size around 1500 chars to keep context intact but focused
            if len(current_chunk) + len(p) > 1500:
                chunks.append(f"### [Source: Page {page.page}]\n{current_chunk.strip()}")
                current_chunk = p + "\n\n"
            else:
                current_chunk += p + "\n\n"
        if current_chunk.strip():
            chunks.append(f"### [Source: Page {page.page}]\n{current_chunk.strip()}")

    if not chunks:
        return ""

    # 2. Setup BM25 index
    tokenized_chunks = [chunk.lower().split() for chunk in chunks]
    bm25 = BM25Okapi(tokenized_chunks)

    # 3. Retrieve top chunks for each ontology concept
    selected_chunks = set()
    for concept, terms in ONTOLOGY.items():
        if concept == "priority_tables":
            continue
        # Use the synonyms as the query
        query = " ".join(terms).lower().split()
        top_k = bm25.get_top_n(query, chunks, n=8)  # Increased from 4 to 8 to capture more qualitative text
        for chunk in top_k:
            selected_chunks.add(chunk)

    # Also query for priority table keywords explicitly
    priority_query = " ".join(ONTOLOGY["priority_tables"]).lower().split()
    top_priority = bm25.get_top_n(priority_query, chunks, n=12)  # Increased from 6 to 12 for massive tables
    for chunk in top_priority:
        selected_chunks.add(chunk)

    # Combine the unique selected chunks
    final_context = ""
    for chunk in selected_chunks:
        if len(final_context) + len(chunk) > max_chars:
            break
        final_context += chunk + "\n\n"

    return final_context
