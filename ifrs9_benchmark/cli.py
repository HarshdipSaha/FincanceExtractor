from __future__ import annotations

import argparse
from pathlib import Path

from .extract import extract_company_benchmark
from .fetch import HttpClient, discover_company_filings, select_latest_comparable
from .report import build_json_report, build_markdown_report


def _parse_company_urls(raw: str) -> list[tuple[str, str]]:
    """Parse comma-separated company=url pairs."""
    results = []
    for part in raw.split(","):
        part = part.strip()
        if "=" in part:
            name, url = part.split("=", 1)
            results.append((name.strip(), url.strip()))
    return results


def _parse_candidate_slugs(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _resolve_urls(
    client: HttpClient,
    company_urls: list[tuple[str, str]],
    candidate_slugs: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Resolve URLs for companies that don't have explicit URLs."""
    resolved = []
    companies_without_url = []

    for name, url in company_urls:
        if url:
            resolved.append((name, url))
        else:
            companies_without_url.append(name)

    if not companies_without_url:
        return resolved

    filings_by_company: dict[str, list] = {}
    for name in companies_without_url:
        slugs = candidate_slugs.get(name, [name.lower().replace(" ", "-")])
        filings: list = []
        for slug in slugs:
            filings.extend(discover_company_filings(client, slug))
        filings_by_company[name] = filings

    if len(companies_without_url) == 2:
        name1, name2 = companies_without_url
        filings1 = filings_by_company.get(name1, [])
        filings2 = filings_by_company.get(name2, [])
        if filings1 and filings2:
            chosen1, chosen2 = select_latest_comparable(filings1, filings2)
            if chosen1 and chosen2:
                resolved.append((name1, chosen1.url))
                resolved.append((name2, chosen2.url))
                return resolved

    for name in companies_without_url:
        filings = filings_by_company.get(name, [])
        if filings:
            sorted_filings = sorted(filings, key=lambda f: f.year, reverse=True)
            resolved.append((name, sorted_filings[0].url))

    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ifrs9-benchmark",
        description="Extract IFRS 9 benchmark data from report links and generate side-by-side output.",
    )
    parser.add_argument(
        "--companies",
        required=True,
        help="Comma-separated company=url pairs (e.g., 'Next plc=https://url,Frasers Group=https://url'). Names only will auto-discover URLs.",
    )
    parser.add_argument(
        "--candidate-slugs",
        default="next-plc,next:frasers-group-plc,frasers-group,frasers",
        help="Colon-separated groups of comma-separated slugs for auto-discovery. Format: 'name1:slugs,name2:slugs'",
    )
    parser.add_argument(
        "--output",
        default="ifrs9_benchmark_report.md",
        help="Output markdown report path.",
    )
    parser.add_argument(
        "--json-output",
        default="ifrs9_benchmark_report.json",
        help="Output structured JSON path.",
    )
    parser.add_argument("--timeout", type=int, default=45, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--max-pdf-pages",
        type=int,
        default=250,
        help="Max pages to parse for PDFs.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    company_urls = _parse_company_urls(args.companies)

    candidate_slugs: dict[str, list[str]] = {}
    for group in args.candidate_slugs.split(":"):
        parts = group.split(",")
        if len(parts) >= 1:
            name = parts[0].strip()
            slugs = [p.strip() for p in parts[1:]] if len(parts) > 1 else [name.lower().replace(" ", "-")]
            candidate_slugs[name] = slugs

    client = HttpClient(timeout=args.timeout)

    resolved = _resolve_urls(client, company_urls, candidate_slugs)

    if len(resolved) < 2:
        raise RuntimeError(
            f"Need at least 2 companies for comparison, got {len(resolved)}. "
            "Pass explicit URLs via --companies 'Name1=https://url1,Name2=https://url2'"
        )

    companies = []
    for name, url in resolved:
        print(f"Extracting data for {name} from {url}...")
        data = extract_company_benchmark(
            client=client,
            company=name,
            report_url=url,
            max_pdf_pages=args.max_pdf_pages,
        )
        companies.append(data)

    markdown = build_markdown_report(companies)
    json_payload = build_json_report(companies)

    output_path = Path(args.output)
    output_path.write_text(markdown, encoding="utf-8")

    json_path = Path(args.json_output)
    json_path.write_text(json_payload, encoding="utf-8")

    print(f"\nResolved {len(companies)} company reports:")
    for name, url in resolved:
        print(f"  - {name}: {url}")
    print(f"\nMarkdown report written to: {output_path.resolve()}")
    print(f"JSON report written to: {json_path.resolve()}")


if __name__ == "__main__":
    main()
