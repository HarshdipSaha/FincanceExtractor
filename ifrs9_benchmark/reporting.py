from __future__ import annotations

import html
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import BenchmarkReport, MetricValue


def render_outputs(report: BenchmarkReport, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark_report.json"
    html_path = output_dir / "benchmark_report.html"
    pdf_path = output_dir / "benchmark_report.pdf"

    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    env = Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["metric"] = metric_text
    env.filters["source"] = source_text
    template = env.get_template("report.html")
    html_text = template.render(report=report)
    html_path.write_text(html_text, encoding="utf-8")

    try:
        from weasyprint import HTML

        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    except Exception:
        _render_pdf_reportlab(report, pdf_path)

    return {"json": json_path, "html": html_path, "pdf": pdf_path}


def metric_text(metric: MetricValue) -> str:
    if metric.value is None:
        return "Not disclosed"
    if isinstance(metric.value, str):
        return metric.value
    number = f"{metric.value:,.2f}".rstrip("0").rstrip(".")
    return f"{number} {html.escape(metric.unit or '')}".strip()


def source_text(metric: MetricValue) -> str:
    source = metric.source
    page = f"p. {source.page}" if source.page else "page not cited"
    title = f", {source.table_or_section}" if source.table_or_section else ""
    return f"{page}{title}"


def _render_pdf_reportlab(report: BenchmarkReport, pdf_path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
    story = [Paragraph(report.title, styles["Title"]), Spacer(1, 12)]
    for firm in report.firms:
        story.append(Paragraph(firm.firm_name, styles["Heading1"]))
        story.append(Paragraph(f"Business model: {firm.business_model or 'Not disclosed'}", styles["BodyText"]))
        story.append(Spacer(1, 8))
        rows = [["Metric", "Value", "Status", "Source"]]
        core = firm.core_ecl_coverage
        for metric in [
            core.gross_customer_receivables,
            core.net_receivables_before_ecl,
            core.ecl_allowance,
            core.net_after_ecl,
            core.derived_coverage_ratio,
        ]:
            rows.append([metric.label, metric_text(metric), metric.disclosure_status, source_text(metric)])
        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
        story.extend([table, Spacer(1, 12)])
    doc.build(story)
