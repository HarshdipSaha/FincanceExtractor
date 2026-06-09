from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import FilingLink


FILING_RE = re.compile(
    r"/filings/(?P<slug>[^/]+)/(?P<kind>annual-report|quarterly-report|half-year-report|interim-report)/(?P<year>20\d{2})(?:/(?P<id>\d+))?/?",
    re.IGNORECASE,
)

PDF_RE = re.compile(r"https?://[^\s\"'>]+\.pdf(?:\?[^\s\"'>]+)?", re.IGNORECASE)


@dataclass(slots=True)
class HttpClient:
    timeout: int = 45

    def _local_path(self, url: str) -> Path | None:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path.lstrip("/")))
        if parsed.scheme:
            return None
        candidate = Path(url)
        if candidate.exists():
            return candidate
        return None

    def get_text(self, url: str) -> str:
        local_path = self._local_path(url)
        if local_path is not None:
            return local_path.read_text(encoding="utf-8")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def get_bytes(self, url: str) -> bytes:
        local_path = self._local_path(url)
        if local_path is not None:
            return local_path.read_bytes()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.content


def extract_filing_links(html: str, base_url: str) -> list[FilingLink]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[tuple[str, str, int, str | None], FilingLink] = {}
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        match = FILING_RE.search(href)
        if not match:
            continue
        absolute = urljoin(base_url, href)
        link = FilingLink(
            slug=match.group("slug").lower(),
            kind=match.group("kind").lower(),
            year=int(match.group("year")),
            filing_id=match.group("id"),
            url=absolute,
        )
        key = (link.slug, link.kind, link.year, link.filing_id)
        found[key] = link
    return list(found.values())


def discover_company_filings(client: HttpClient, slug: str) -> list[FilingLink]:
    urls = [
        f"https://financialreports.eu/companies/{slug}/",
        f"https://financialreports.eu/filings/{slug}/",
        f"https://financialreports.eu/companies/search/?q={slug}",
    ]
    found: dict[tuple[str, str, int, str | None], FilingLink] = {}
    for url in urls:
        try:
            html = client.get_text(url)
        except Exception:
            continue
        for link in extract_filing_links(html, url):
            key = (link.slug, link.kind, link.year, link.filing_id)
            found[key] = link
    return list(found.values())


def filing_priority(kind: str) -> int:
    ranking = {
        "annual-report": 4,
        "half-year-report": 3,
        "interim-report": 2,
        "quarterly-report": 1,
    }
    return ranking.get(kind.lower(), 0)


def select_latest_comparable(
    first: list[FilingLink], second: list[FilingLink]
) -> tuple[FilingLink | None, FilingLink | None]:
    first_map = {(item.year, item.kind): item for item in first}
    second_map = {(item.year, item.kind): item for item in second}

    common = []
    for key in set(first_map).intersection(second_map):
        year, kind = key
        common.append((year, filing_priority(kind), kind))

    if common:
        common.sort(reverse=True)
        chosen_year, _, chosen_kind = common[0]
        return first_map[(chosen_year, chosen_kind)], second_map[(chosen_year, chosen_kind)]

    first_sorted = sorted(first, key=lambda item: (item.year, filing_priority(item.kind)), reverse=True)
    second_sorted = sorted(second, key=lambda item: (item.year, filing_priority(item.kind)), reverse=True)
    return (first_sorted[0] if first_sorted else None, second_sorted[0] if second_sorted else None)


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        if ".pdf" in href.lower():
            links.add(urljoin(base_url, href))

    for match in PDF_RE.finditer(html):
        links.add(urljoin(base_url, match.group(0)))

    # Priority: direct report-like links before generic attachments.
    prioritized = sorted(
        links,
        key=lambda link: (
            "annual" not in link.lower() and "report" not in link.lower(),
            "download" not in link.lower(),
            len(link),
        ),
    )
    return prioritized
