from __future__ import annotations

import re

from .models import FirmReport, MetricValue
from .parser import PageBlock


def validate_citations(report: FirmReport, pages: list[PageBlock]) -> FirmReport:
    page_text = {page.page: page.text.lower() for page in pages}
    warnings: list[str] = []

    for metric in _iter_metrics(report):
        source_page = metric.source.page
        if metric.value is None or isinstance(metric.value, str) or not isinstance(source_page, int):
            continue
        text = page_text.get(source_page, "")
        if not text:
            warnings.append(f"{metric.label}: cited page {source_page} was not in extracted context.")
            metric.confidence = "LOW"
            continue
        if not _number_visible(metric.value, text):
            warnings.append(f"{metric.label}: value {metric.value} was not found verbatim on cited page {source_page}; review citation.")
            if metric.disclosure_status != "DERIVED":
                metric.confidence = "LOW"
    report.extraction_warnings.extend(warnings)
    return report


def _iter_metrics(report: FirmReport):
    core = report.core_ecl_coverage
    yield core.gross_customer_receivables
    yield core.net_receivables_before_ecl
    yield core.ecl_allowance
    yield core.net_after_ecl
    yield core.derived_coverage_ratio
    for row in report.staging_table:
        yield row.gross_exposure
        yield row.ecl_allowance
        yield row.net_exposure
        yield row.coverage_ratio
    for row in report.impairment_movement_table:
        yield row.opening
        yield row.charge_release
        yield row.charge_offs_or_movement
        yield row.write_offs
        yield row.closing
    details = report.model_design_details
    for value in details.model_fields:
        yield getattr(details, value)


def _number_visible(value: float, text: str) -> bool:
    candidates = {
        f"{value:g}",
        f"{value:,.0f}",
        f"{value:.1f}",
        f"{abs(value):g}",
        f"{abs(value):,.0f}",
        f"{abs(value):.1f}",
    }
    compact_text = text.replace(",", "")
    for candidate in candidates:
        if candidate.lower().replace(",", "") in compact_text:
            return True
    return False
