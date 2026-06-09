from __future__ import annotations

import re
from collections import defaultdict

from .fetch import HttpClient, extract_pdf_links
from .models import (
    AgeingBucket,
    CompanyBenchmark,
    Evidence,
    ExtractedField,
    PageData,
    SourceDocument,
    StageMovement,
    TableData,
)
from .parse import load_document, report_period_from_url
from .utils import (
    best_sentences,
    contains_any,
    first_number,
    normalize_space,
    parse_number,
    safe_ratio,
    split_sentences,
)


NUMBER_CAPTURE = r"(\(?-?\d[\d,]*(?:\.\d+)?\)?)"


def _field(value: str | None, snippets: list[str], source_url: str, location: str | None = None) -> ExtractedField:
    evidence = [Evidence(text=normalize_space(s), source_url=source_url, location=location) for s in snippets if normalize_space(s)]
    return ExtractedField(value=value, evidence=evidence)


def _page_location(page: PageData | None) -> str | None:
    return f"page-{page.page_number}" if page is not None else None


def _table_text(table: TableData) -> str:
    return " ".join(table.columns + [cell for row in table.rows for cell in row])


def _all_pages(docs: list[SourceDocument]) -> list[PageData]:
    pages: list[PageData] = []
    for doc in docs:
        pages.extend(doc.pages)
    return pages


def _topic_pages(pages: list[PageData], keywords: list[str], limit: int = 8) -> list[PageData]:
    scored: list[tuple[int, int, PageData]] = []
    for page in pages:
        text = page.text.lower()
        score = sum(3 if kw in text else 0 for kw in keywords)
        score += sum(2 for table in page.tables if any(kw in _table_text(table).lower() for kw in keywords))
        if score > 0:
            scored.append((score, -page.page_number, page))
    scored.sort(reverse=True)
    chosen: list[PageData] = []
    seen: set[int] = set()
    for _, _, page in scored:
        if page.page_number in seen:
            continue
        chosen.append(page)
        seen.add(page.page_number)
        if len(chosen) >= limit:
            break
    return chosen


def _topic_tables(pages: list[PageData]) -> list[TableData]:
    tables: list[TableData] = []
    for page in pages:
        tables.extend(page.tables)
    return tables


def _page_snippets(pages: list[PageData], keywords: list[str], limit: int = 4) -> list[Evidence]:
    evidence: list[Evidence] = []
    for page in pages:
        for sentence in best_sentences(page.text, keywords, limit=2):
            evidence.append(Evidence(text=sentence, source_url=page.source_url, location=_page_location(page)))
            if len(evidence) >= limit:
                return evidence
    return evidence


def _detect_unit(text: str) -> str | None:
    low = text.lower()
    if "£bn" in low or "łbn" in low:
        return "GBP bn"
    if "£m" in low or "łm" in low:
        return "GBP m"
    return None


def _classify_company_type(company: str, text: str) -> str | None:
    low = f"{company} {text}".lower()
    if "markets plc" in low or "investment bank" in low or "markets business" in low:
        return "Investment / markets bank"
    if "commercial bank" in low or ("retail" in low and "commercial" in low):
        return "Retail + commercial bank"
    if "retail banking division" in low or "ring-fenced uk retail banking division" in low:
        return "Retail bank"
    if "retail bank" in low:
        return "Retail bank"
    return None


def _pick_best_table(tables: list[TableData], keywords: list[str]) -> TableData | None:
    best: tuple[int, TableData] | None = None
    for table in tables:
        text = " ".join(table.columns + [cell for row in table.rows for cell in row]).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, table)
    return best[1] if best else None


def _row_value(row: list[str]) -> float | None:
    for cell in row[1:]:
        value = first_number(cell)
        if value is not None:
            return value
    if row:
        return first_number(row[0])
    return None


def _extract_values_from_table(table: TableData) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in table.rows:
        if not row:
            continue
        key = row[0].lower()
        value = _row_value(row)
        if value is None:
            continue
        values[key] = value
    return values


def _is_year_like(value: float) -> bool:
    absolute = abs(value)
    return absolute.is_integer() and 1900 <= absolute <= 2100


def _select_row_number(row: list[str], key: str) -> float | None:
    numbers = [parse_number(cell) for cell in row[1:]]
    numbers = [n for n in numbers if n is not None]
    if not numbers:
        return None

    non_year_numbers = [n for n in numbers if not _is_year_like(n)]
    if non_year_numbers:
        numbers = non_year_numbers

    low = key.lower()
    if contains_any(low, ["loans by stage and asset quality", "gross exposure", "net exposure", "total exposure", "ecl provisions by stage"]):
        return numbers[-1]
    if contains_any(low, ["allowance", "impairment", "provision", "loss allowance", "expected credit loss"]):
        for number in numbers:
            if number < 0:
                return number
        chosen = max(numbers, key=lambda n: abs(n))
        if contains_any(low, ["less", "allowance", "impairment", "provision", "loss"]):
            return -abs(chosen)
        return chosen
    return numbers[0]


def _gross_row_score(key: str) -> int:
    low = key.lower()
    score = 0
    if contains_any(low, ["gross customer receivables", "gross trade receivables", "gross receivables"]):
        score += 7
    elif contains_any(low, ["gross exposure", "total exposure", "loan exposure", "loans by stage and asset quality"]):
        score += 6
    elif contains_any(low, ["gross value", "gross carrying amount"]):
        score += 5
    elif contains_any(low, ["total loans", "loans to customers", "in scope of ifrs 9 ecl framework"]):
        score += 4
    elif "gross" in low:
        score += 2
    if "net" in low:
        score -= 3
    return score


def _allowance_row_score(key: str) -> int:
    low = key.lower()
    score = 0
    if "allowance for expected credit loss" in low:
        score += 8
    if "allowance for expected credit losses" in low:
        score += 8
    if "provision for impairment" in low:
        score += 7
    if contains_any(low, ["allowance", "impairment", "loss allowance", "expected credit loss", "provision"]):
        score += 4
    if "less" in low:
        score += 3
    if contains_any(low, ["reversal", "charge", "movement", "opening", "closing"]):
        score -= 3
    return score


def _net_row_score(key: str) -> int:
    low = key.lower()
    score = 0
    if contains_any(low, ["net receivables", "net exposure", "net carrying amount", "net loans", "net assets"]):
        score += 6
    elif "net" in low:
        score += 2
    if "gross" in low:
        score -= 2
    return score


def _extract_metric_from_text(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = parse_number(match.group(1))
        if value is not None:
            return value
    return None


def _sum_stage_rows(table: TableData, row_prefix: str, stage_labels: tuple[str, ...] = ("stage 1", "stage 2", "stage 3")) -> float | None:
    values: list[float] = []
    for row in table.rows:
        if not row:
            continue
        label = row[0].lower().strip()
        if label not in stage_labels and not any(label.endswith(stage) for stage in stage_labels):
            continue
        value = _select_row_number(row, f"{row_prefix} {label}")
        if value is None:
            continue
        values.append(abs(value))
    if len(values) >= 2:
        return sum(values)
    return None


def _extract_natwest_like_core(page: PageData) -> tuple[float | None, float | None, TableData | None, str | None]:
    for table in page.tables:
        text = _table_text(table).lower()
        if "loans by stage and asset quality" not in text or "ecl provisions by stage" not in text:
            continue
        gross = None
        allowance = None
        for row in table.rows:
            if not row:
                continue
            label = row[0].lower()
            if "loans by stage and asset quality" in label:
                gross = _select_row_number(row, row[0])
            elif "ecl provisions by stage" in label:
                allowance = _select_row_number(row, row[0])
        if gross is not None and allowance is not None:
            return abs(gross), -abs(allowance), table, "Third-party loans within ECL framework"
    return None, None, None, None


def _extract_santander_like_core(page: PageData) -> tuple[float | None, float | None, TableData | None, str | None]:
    for table in page.tables:
        labels = [row[0].lower() for row in table.rows if row]
        if not any("at 31 december 2025" in label for label in labels):
            continue
        if not any("transfers from stage 1 to stage 2" in label for label in labels):
            continue
        for row in table.rows:
            if not row or "at 31 december 2025" not in row[0].lower():
                continue
            numbers = [parse_number(cell) for cell in row[1:]]
            numbers = [n for n in numbers if n is not None]
            if len(numbers) < 8:
                continue
            # Stage 1 exposure/ECL, Stage 2 exposure/ECL, Stage 3 exposure/ECL, Total exposure/ECL
            gross = numbers[6] if len(numbers) >= 7 else None
            allowance = numbers[7] if len(numbers) >= 8 else None
            if gross is not None and allowance is not None:
                return abs(gross), abs(allowance) * (-1 if allowance > 0 else 1), table, "Closing on-balance-sheet ECL exposure"
    return None, None, None, None


def _extract_barclays_like_core(pages: list[PageData]) -> tuple[float | None, float | None, TableData | None, str | None]:
    total_ecl = None
    total_ecl_page: PageData | None = None
    gross = None
    gross_page: PageData | None = None

    for page in pages:
        lines = page.text.splitlines()
        if total_ecl is None:
            for line in lines:
                low = line.lower()
                if "total weighted model ecl" in low:
                    continue
                if low.strip().startswith("total ecl"):
                    value = first_number(line)
                    if value is not None:
                        total_ecl = abs(value)
                        total_ecl_page = page
                        break
        if gross is None:
            for line in lines:
                low = line.lower()
                if "gross loans and advances" in low:
                    value = first_number(line)
                    if value is not None:
                        gross = abs(value)
                        gross_page = page
                        break
    if gross is not None and total_ecl is not None:
        synthetic_table = TableData(
            title="Cross-page core metrics",
            columns=["Metric", "Value"],
            rows=[
                ["Gross loans and advances", f"{gross:.1f}"],
                ["Total ECL", f"({total_ecl:.1f})"],
            ],
            source_url=pages[0].source_url if pages else "",
            location=f"{_page_location(gross_page) or ''} / {_page_location(total_ecl_page) or ''}".strip(" /"),
        )
        return gross, -total_ecl, synthetic_table, "Gross loans and advances vs Total ECL (cross-page)"
    return None, None, None, None


def _extract_core_metrics(text: str, tables: list[TableData]) -> tuple[float | None, float | None, TableData | None]:
    candidate = None
    gross = None
    allowance = None
    best_score: tuple[int, int, float] | None = None

    for table in tables:
        table_gross: tuple[int, float] | None = None
        table_allowance: tuple[int, float] | None = None
        table_net: tuple[int, float] | None = None
        labels = [row[0].lower() for row in table.rows if row]
        has_loss_context = any(
            contains_any(label, ["allowance", "impairment", "expected credit loss", "ecl", "provision"])
            for label in labels
        )

        for row in table.rows:
            if not row:
                continue
            key = row[0]
            value = _select_row_number(row, key)
            if value is None:
                continue

            gross_score = _gross_row_score(key)
            allowance_score = _allowance_row_score(key)
            net_score = _net_row_score(key)

            if gross_score > 0:
                candidate_score = (gross_score, abs(value))
                if table_gross is None or candidate_score > (table_gross[0], abs(table_gross[1])):
                    table_gross = (gross_score, value)
            if allowance_score > 0:
                candidate_score = (allowance_score, abs(value))
                if table_allowance is None or candidate_score > (table_allowance[0], abs(table_allowance[1])):
                    table_allowance = (allowance_score, value)
            if net_score > 0:
                candidate_score = (net_score, abs(value))
                if table_net is None or candidate_score > (table_net[0], abs(table_net[1])):
                    table_net = (net_score, value)

        if table_allowance is None and has_loss_context and table_gross is not None and table_net is not None:
            derived_allowance = table_net[1] - abs(table_gross[1])
            if derived_allowance != 0:
                table_allowance = (table_net[0], derived_allowance)

        quality = 0
        if table_gross is not None:
            quality += table_gross[0]
        if table_allowance is not None:
            quality += table_allowance[0] + 4
        if table_net is not None:
            quality += table_net[0]
        if table_gross is None or table_allowance is None:
            continue

        score = (quality, len(table.rows), abs(table_gross[1]))
        if best_score is None or score > best_score:
            best_score = score
            candidate = table
            gross = abs(table_gross[1])
            allowance = table_allowance[1]

    if gross is None:
        gross = _extract_metric_from_text(
            text,
            [
                rf"gross\s+(?:customer\s+)?receivables[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"gross\s+carrying\s+amount[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"trade\s+receivables[^0-9\-()]*gross[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"gross\s+exposure[^0-9\-()]*{NUMBER_CAPTURE}",
            ],
        )
    if allowance is None:
        allowance = _extract_metric_from_text(
            text,
            [
                rf"ecl\s+allowance[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"loss\s+allowance[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"impairment\s+allowance[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"expected\s+credit\s+loss(?:es)?\s+allowance[^0-9\-()]*{NUMBER_CAPTURE}",
                rf"ecl\s+provisions?[^0-9\-()]*{NUMBER_CAPTURE}",
            ],
        )
    return gross, allowance, candidate


def _extract_model_structure(text: str, source_url: str) -> ExtractedField:
    low = text.lower()
    pieces: list[str] = []
    has_three_stage = "stage 1" in low and "stage 2" in low and "stage 3" in low
    if has_three_stage:
        pieces.append("3-stage IFRS 9 model")
    elif "simplified approach" in low or "always lifetime" in low:
        pieces.append("Simplified approach (lifetime ECL)")
    if not pieces and "lifetime expected credit losses" in low:
        pieces.append("Lifetime ECL approach")

    seg_sentences = best_sentences(
        text,
        ["stage 1", "stage 2", "stage 3", "simplified approach", "lifetime expected credit losses", "segmentation", "arrears", "bucket", "indebtedness", "behavioural", "behavioral"],
        limit=4,
    )
    if seg_sentences:
        pieces.append("Segmentation logic disclosed")

    value = "; ".join(pieces) if pieces else None
    return _field(value, seg_sentences[:2], source_url)


def _extract_scenario_design(text: str, source_url: str) -> ExtractedField:
    keywords = [
        "scenario",
        "weight",
        "base case",
        "upside",
        "downside",
        "severe downside",
        "macroeconomic",
    ]
    raw_evidence = best_sentences(text, keywords, limit=6)
    evidence = list(dict.fromkeys(raw_evidence))[:4]
    scenario_names: set[str] = set()
    full_text_low = text.lower()
    full_text_names = {
        "Base": "base case" in full_text_low or re.search(r"\bbase\b", full_text_low) is not None,
        "Upside": "upside" in full_text_low,
        "Downside": "downside" in full_text_low,
        "Extreme": "extreme downside" in full_text_low or "severe downside" in full_text_low or "severe case" in full_text_low,
    }
    scenario_names.update(name for name, present in full_text_names.items() if present)
    for sentence in evidence:
        for name in [
            "base",
            "upside",
            "downside",
            "severe downside",
            "severe-case",
            "severe case",
            "extreme",
            "optimistic",
            "pessimistic",
            "central",
        ]:
            if name in sentence.lower():
                normalized = name.title()
                if name in {"severe downside", "severe-case", "severe case", "extreme"}:
                    normalized = "Extreme"
                scenario_names.add(normalized)

    weight_map: dict[str, str] = {}
    scenario_pattern = re.compile(r"base(?:\s+case)?|upside|downside|severe(?:[-\s]case|[-\s]downside)?|extreme", re.IGNORECASE)
    for sentence in evidence:
        sentence_low = sentence.lower()
        explicit_patterns = {
            "Base": [
                r"(\d{1,3}(?:\.\d+)?)\s*%\s+weighting\s+is\s+applied\s+to\s+the\s+base",
                r"base(?:\s+case)?.{0,120}?\bto\s+(\d{1,3}(?:\.\d+)?)\s*%",
            ],
            "Upside": [
                r"(\d{1,3}(?:\.\d+)?)\s*%\s+to\s+the\s+upside",
                r"upside.{0,120}?\bto\s+(\d{1,3}(?:\.\d+)?)\s*%",
            ],
            "Downside": [
                r"(\d{1,3}(?:\.\d+)?)\s*%\s+to\s+the\s+downside",
                r"downside.{0,120}?(?:\bto|\bremaining at)\s+(\d{1,3}(?:\.\d+)?)\s*%",
            ],
            "Extreme": [
                r"(\d{1,3}(?:\.\d+)?)\s*%\s+to\s+the\s+extreme",
                r"(?:extreme|severe(?:[-\s]case|[-\s]downside)?).{0,120}?\bto\s+(\d{1,3}(?:\.\d+)?)\s*%",
                r"(?:extreme|severe(?:[-\s]case|[-\s]downside)?).{0,120}?\bat\s+(\d{1,3}(?:\.\d+)?)\s*%",
            ],
        }
        for scenario_name, patterns in explicit_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, sentence_low)
                if match:
                    weight_map.setdefault(scenario_name, match.group(1))
                    break

        scenario_order: list[str] = []
        for match in scenario_pattern.finditer(sentence_low):
            token = match.group(0)
            if token.startswith("base"):
                normalized = "Base"
            elif token.startswith("upside"):
                normalized = "Upside"
            elif token.startswith("downside"):
                normalized = "Downside"
            else:
                normalized = "Extreme"
            if normalized not in scenario_order:
                scenario_order.append(normalized)
        percentages = re.findall(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", sentence)
        if len(scenario_order) < 2 or len(percentages) < 2:
            continue
        for idx, scenario_name in enumerate(scenario_order):
            if idx >= len(percentages):
                break
            weight_map.setdefault(scenario_name, percentages[idx])
    value_parts = []
    if scenario_names:
        preferred_order = ["Base", "Upside", "Downside", "Extreme", "Central", "Optimistic", "Pessimistic"]
        ordered = [name for name in preferred_order if name in scenario_names]
        extras = sorted(scenario_names - set(ordered))
        ordered.extend(extras)
        value_parts.append(f"{len(ordered)} scenarios: {', '.join(ordered)}")
    weights = [weight_map[name] for name in ordered if name in weight_map] if scenario_names else []
    if not weights:
        weights = re.findall(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", " ".join(evidence))
    if weights:
        value_parts.append(f"weights: {'/'.join(weights)}")
    value = "; ".join(value_parts) if value_parts else None
    return _field(value, evidence, source_url)


def _extract_key_parameters(text: str, source_url: str) -> ExtractedField:
    pd = best_sentences(text, ["pd", "probability of default"], limit=2)
    lgd = best_sentences(text, ["lgd", "loss given default"], limit=2)
    ead = best_sentences(text, ["ead", "exposure at default"], limit=2)
    fwd = best_sentences(
        text,
        ["unemployment", "gdp", "inflation", "interest rate", "house price", "forward-looking", "macro"],
        limit=3,
    )

    summary = []
    if pd:
        summary.append("PD disclosed")
    if lgd:
        summary.append("LGD disclosed")
    if ead:
        summary.append("EAD disclosed")
    if fwd:
        summary.append("Forward-looking variables disclosed")
    value = "; ".join(summary) if summary else None
    return _field(value, (pd + lgd + ead + fwd)[:6], source_url)


def _extract_staging_table(tables: list[TableData]) -> TableData | None:
    best: tuple[int, TableData] | None = None
    for table in tables:
        score = 0
        text = " ".join(table.columns + [cell for row in table.rows for cell in row]).lower()
        if "stage 1" in text and "stage 2" in text and "stage 3" in text:
            score += 6
        labels = [row[0].lower() for row in table.rows if row]
        if any("gross" in label and "receivable" in label for label in labels):
            score += 4
        if any(contains_any(label, ["allowance", "impairment", "expected credit loss", "ecl provisions by stage"]) for label in labels):
            score += 4
        if any("coverage" in label for label in labels):
            score += 5
        if any("loans by stage" in label or "exposure by stage" in label for label in labels):
            score += 5
        if any("opening" in label for label in labels) and any("closing" in label for label in labels):
            score -= 3
        if any("transfer" in label for label in labels):
            score -= 4
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, table)
    return best[1] if best else None


def _extract_ageing_table(tables: list[TableData]) -> TableData | None:
    return _pick_best_table(tables, ["past due", "not past due", "0-60", "60-120", "120+", "dpd", "ageing", "delinquency"])


def _parse_ageing_buckets(table: TableData | None, use_columns: dict[int, str] | None = None) -> list[AgeingBucket]:
    """Parse ageing table into structured bucket data.

    Args:
        table: The table to parse
        use_columns: Optional dict mapping column index to stage name (for hybrid tables)
    """
    if not table:
        return []

    buckets: list[AgeingBucket] = []
    bucket_patterns = {
        "not past due": [r"(?:not|never)\s*(?:past\s*due|overdue|dpd)", r"^not\s+past\s+due$"],
        "0-60 days": [r"0?\s*[-–/]\s*60", r"up to 60", r"within 60", r"1?\s*[-–/]\s*60"],
        "60-120 days": [r"60\s*[-–/]\s*120", r"60\s*[-–/]\s*90", r"two to four months"],
        "120+ days": [r"120\s*\+", r"120\s*plus", r"over 120", r"90\s*\+", r"three months\+", r"default"],
        "90-120 days": [r"90\s*[-–/]\s*120", r"90\s*[-–/]\s*119"],
        "30-60 days": [r"30\s*[-–/]\s*60", r"30\s*[-–/]\s*59", r"one to two months"],
        "60-90 days": [r"60\s*[-–/]\s*90", r"60\s*[-–/]\s*89", r"two to three months"],
        "0-30 days": [r"0?\s*[-–/]\s*30", r"up to 30", r"within 30", r"less than 30"],
    }

    seen_buckets: set[str] = set()

    for row in table.rows:
        if not row:
            continue
        label = row[0].lower()

        # Skip non-ageing rows
        if "stage" in label or "opening" in label or "closing" in label or "charge" in label or "impairment" in label:
            continue
        if "gross trade" in label or "allowance for" in label:
            continue

        matched_bucket = None
        for bucket_name, patterns in bucket_patterns.items():
            if bucket_name in seen_buckets:
                continue
            for pattern in patterns:
                if re.search(pattern, label, re.IGNORECASE):
                    matched_bucket = bucket_name
                    break
            if matched_bucket:
                break

        if not matched_bucket:
            continue

        # For hybrid tables with column structure (like Frasers), use specific columns
        gross = None
        allowance = None

        if use_columns:
            # Use the first stage column for gross amount
            for col_idx in sorted(use_columns.keys()):
                if col_idx < len(row):
                    val = parse_number(row[col_idx])
                    if val is not None and val >= 0 and gross is None:
                        gross = val
                        break
            # Check for allowance in the same row from a different context
            # In Frasers table: row 1 = Not past due amounts, row 2 = Gross totals, row 3 = Allowances
            row_idx = table.rows.index(row)
            if row_idx > 0 and row_idx < len(table.rows):
                # Look at "Allowance for expected credit loss" row for the same column
                for other_row in table.rows:
                    if other_row and "allowance for expected credit loss" in other_row[0].lower():
                        for col_idx in sorted(use_columns.keys()):
                            if col_idx < len(other_row):
                                val = parse_number(other_row[col_idx])
                                if val is not None and val < 0:
                                    allowance = val
                                    break
                        break
        else:
            for cell in row[1:]:
                val = parse_number(cell)
                if val is not None:
                    if val < 0:
                        if allowance is None:
                            allowance = val
                    elif gross is None:
                        gross = val

        coverage = safe_ratio(abs(allowance) if allowance else None, abs(gross) if gross else None)
        buckets.append(AgeingBucket(
            bucket_name=matched_bucket.title(),
            gross_amount=gross,
            allowance_amount=allowance,
            coverage_ratio=coverage,
        ))
        seen_buckets.add(matched_bucket)

    return buckets


def _extract_impairment_movement_table(tables: list[TableData]) -> TableData | None:
    return _pick_best_table(tables, ["opening", "charge", "write-off", "closing", "stage", "impairment", "movement"])


def _parse_stage_movements(table: TableData | None) -> list[StageMovement]:
    """Parse impairment movement table into structured stage-level data.

    Handles two formats:
    1. Column-based: Columns named "Stage 1", "Stage 2", etc. (standard)
    2. Row-based: A "Stage" row with values 1, 2, 3 indicating column meanings (Frasers style)
    """
    if not table:
        return []

    movements: dict[str, StageMovement] = {}
    stage_pattern = re.compile(r"stage\s*([123])", re.IGNORECASE)

    # Detect column-based stage layout from column headers
    lower_columns = [c.lower() for c in table.columns]
    stage_col_indices: dict[int, str] = {}
    for idx, col in enumerate(lower_columns):
        match = stage_pattern.search(col)
        if match:
            stage_col_indices[idx] = f"Stage {match.group(1)}"

    # If no column headers, look for "Stage" row (Frasers hybrid format)
    if not stage_col_indices:
        for row in table.rows:
            if row and row[0].lower().strip() == "stage":
                for idx, cell in enumerate(row[1:], start=1):
                    if cell.strip() in ("1", "2", "3"):
                        stage_col_indices[idx] = f"Stage {cell.strip()}"
                break

    # Wide pair layout: Stage 1 assets/ECL, Stage 2 assets/ECL, Stage 3 assets/ECL, Total assets/ECL
    if not stage_col_indices and any(len(row) >= 7 for row in table.rows):
        labels = [row[0].lower() for row in table.rows if row]
        if any("at 1 january" in label for label in labels) and any("written-off" in label or "written off" in label for label in labels):
            stage_col_indices = {2: "Stage 1", 4: "Stage 2", 6: "Stage 3"}

    row_types = {
        "opening": ["opening", "balance at start", "brought forward", "opening balance", "at 1 january", "at 1 jan"],
        "charge": ["charge", "impairment charge", "provision charge", "new provisions", "additional", "income statement"],
        "write_offs": ["write-off", "write off", "utilised", "utilized", "used", "released", "written-off", "written off"],
        "closing": ["closing", "balance at end", "carried forward", "closing balance", "at 31 december", "at 31 dec"],
    }

    # Stage-indexed layout (columns represent stages)
    if stage_col_indices:
        for row in table.rows:
            if not row:
                continue
            label = row[0].lower()

            row_type = None
            for rt, keywords in row_types.items():
                if any(kw in label for kw in keywords):
                    row_type = rt
                    break

            if not row_type:
                continue

            for col_idx, stage_key in stage_col_indices.items():
                if col_idx >= len(row):
                    continue
                if stage_key not in movements:
                    movements[stage_key] = StageMovement(stage=stage_key)

                val = parse_number(row[col_idx])
                if val is None:
                    continue
                if row_type == "opening":
                    if movements[stage_key].opening is None:
                        movements[stage_key].opening = val
                elif row_type == "charge":
                    if movements[stage_key].charge is None:
                        movements[stage_key].charge = val
                elif row_type == "write_offs":
                    if movements[stage_key].write_offs is None:
                        movements[stage_key].write_offs = val
                elif row_type == "closing":
                    if movements[stage_key].closing is None:
                        movements[stage_key].closing = val
    else:
        # Row-based stage layout (each row is a stage)
        for row in table.rows:
            if not row:
                continue
            label = row[0].lower()

            stage_match = stage_pattern.search(label)
            if not stage_match:
                continue
            stage_num = stage_match.group(1)
            stage_key = f"Stage {stage_num}"

            if stage_key not in movements:
                movements[stage_key] = StageMovement(stage=stage_key)

            row_type = None
            for rt, keywords in row_types.items():
                if any(kw in label for kw in keywords):
                    row_type = rt
                    break

            if not row_type:
                continue

            for cell in row[1:]:
                val = parse_number(cell)
                if val is None:
                    continue
                if row_type == "opening":
                    movements[stage_key].opening = val
                elif row_type == "charge":
                    movements[stage_key].charge = val
                elif row_type == "write_offs":
                    movements[stage_key].write_offs = val
                elif row_type == "closing":
                    movements[stage_key].closing = val

    return list(movements.values())


def _append_stage_coverage_note(company: CompanyBenchmark) -> None:
    table = company.staging_table
    if not table:
        return
    lower_columns = [col.lower() for col in table.columns]
    stage_indices = {}
    for idx, col in enumerate(lower_columns):
        if "stage 1" in col:
            stage_indices["Stage 1"] = idx
        elif "stage 2" in col:
            stage_indices["Stage 2"] = idx
        elif "stage 3" in col:
            stage_indices["Stage 3"] = idx
    if not stage_indices:
        stage_rows: dict[str, float] = {}
        coverage_rows: dict[str, float] = {}
        for row in table.rows:
            if not row:
                continue
            label = row[0].lower()
            if label in {"stage 1", "stage 2", "stage 3"}:
                value = first_number(row[-1]) if row else None
                if value is not None:
                    stage_rows[label.title()] = value
            if "coverage" in label and "stage" in label:
                match = re.search(r"stage\s*([123])", label)
                if not match:
                    continue
                value = first_number(" ".join(row[1:]))
                if value is not None:
                    coverage_rows[f"Stage {match.group(1)}"] = value / 100
        if coverage_rows:
            parts = [f"{stage}: {ratio * 100:.1f}%" for stage, ratio in sorted(coverage_rows.items())]
            company.notes.append("Stage-level coverage ratios -> " + ", ".join(parts))
        return

    gross_row = None
    allowance_row = None
    for row in table.rows:
        if not row:
            continue
        label = row[0].lower()
        if "gross" in label:
            gross_row = row
        if "allowance" in label or "impairment" in label or "expected credit loss" in label:
            allowance_row = row
    if not gross_row or not allowance_row:
        return

    parts = []
    for stage_name, idx in sorted(stage_indices.items()):
        if idx >= len(gross_row) or idx >= len(allowance_row):
            continue
        gross = first_number(gross_row[idx])
        allowance = first_number(allowance_row[idx])
        if gross is None or allowance is None or gross == 0:
            continue
        ratio = abs(allowance) / abs(gross)
        parts.append(f"{stage_name}: {ratio * 100:.1f}%")
    if parts:
        company.notes.append("Stage-level coverage ratios -> " + ", ".join(parts))


def _detect_stage_columns(table: TableData) -> dict[int, str]:
    """Detect which columns represent stages, from either headers or a 'Stage' row."""
    stage_pattern = re.compile(r"stage\s*([123])", re.IGNORECASE)
    stage_col_indices: dict[int, str] = {}

    # Try column headers first
    lower_columns = [c.lower() for c in table.columns]
    for idx, col in enumerate(lower_columns):
        match = stage_pattern.search(col)
        if match:
            stage_col_indices[idx] = f"Stage {match.group(1)}"

    # If no headers, look for "Stage" row (Frasers hybrid format)
    if not stage_col_indices:
        for row in table.rows:
            if row and row[0].lower().strip() == "stage":
                for idx, cell in enumerate(row[1:], start=1):
                    if cell.strip() in ("1", "2", "3"):
                        stage_col_indices[idx] = f"Stage {cell.strip()}"
                break

    return stage_col_indices


def _extract_ageing_analysis(company: CompanyBenchmark) -> None:
    """Extract structured ageing bucket data from the ageing table."""
    stage_columns: dict[int, str] = {}
    if company.staging_table:
        stage_columns = _detect_stage_columns(company.staging_table)

    if company.ageing_table:
        company.ageing_buckets = _parse_ageing_buckets(company.ageing_table)

    # Also try staging table if it has "Not past due" rows (Frasers style hybrid table)
    if not company.ageing_buckets and company.staging_table:
        company.ageing_buckets = _parse_ageing_buckets(company.staging_table, stage_columns if stage_columns else None)

    if company.ageing_buckets:
        total_gross = sum(b.gross_amount or 0 for b in company.ageing_buckets)
        if total_gross > 0:
            bucket_120_plus = next((b for b in company.ageing_buckets if "120" in b.bucket_name or "90" in b.bucket_name), None)
            if bucket_120_plus and bucket_120_plus.gross_amount:
                pct = (bucket_120_plus.gross_amount / total_gross) * 100
                company.notes.append(f"Ageing analysis: {pct:.1f}% of book is 120+ DPD")


def _extract_impairment_analysis(company: CompanyBenchmark) -> None:
    """Extract structured impairment movement data from the movement table."""
    if company.impairment_movement_table:
        company.stage_movements = _parse_stage_movements(company.impairment_movement_table)
        if company.stage_movements:
            stage3 = next((s for s in company.stage_movements if s.stage == "Stage 3"), None)
            if stage3 and stage3.write_offs:
                company.notes.append(f"Impairment movement: Stage 3 write-offs = {abs(stage3.write_offs):.1f}")


def _collect_documents(client: HttpClient, report_url: str, max_pdf_pages: int) -> list[SourceDocument]:
    primary = load_document(client, report_url, max_pdf_pages=max_pdf_pages)
    docs = [primary]
    if primary.document_type == "html":
        pdf_links: list[str] = []
        # Also parse HTML source for real links.
        try:
            html_raw = client.get_text(report_url)
            pdf_links = extract_pdf_links(html_raw, report_url) or pdf_links
        except Exception:
            pass
        for pdf_link in pdf_links[:2]:
            try:
                docs.append(load_document(client, pdf_link, max_pdf_pages=max_pdf_pages))
            except Exception:
                continue
    return docs


def extract_company_benchmark(
    client: HttpClient,
    company: str,
    report_url: str,
    max_pdf_pages: int = 250,
) -> CompanyBenchmark:
    docs = _collect_documents(client, report_url, max_pdf_pages=max_pdf_pages)
    source_anchor = docs[0].url if docs else report_url
    pages = _all_pages(docs)
    merged_text = "\n".join(page.text for page in pages)
    all_tables = _topic_tables(pages)

    model_pages = _topic_pages(pages, ["stage 1", "stage 2", "stage 3", "simplified approach", "lifetime expected credit losses", "sigr", "sicr"])
    scenario_pages = _topic_pages(pages, ["scenario", "weight", "base case", "upside", "downside", "severe downside", "macroeconomic"])
    key_param_pages = _topic_pages(pages, ["probability of default", "pd", "loss given default", "lgd", "exposure at default", "ead", "forward-looking", "macro"])
    core_pages = _topic_pages(pages, ["loan impairment provisions", "loan exposure", "impairment allowance", "total ecl", "gross loans and advances", "gross exposure", "coverage ratio", "total coverage", "ecl provisions by stage", "loans by stage and asset quality"], limit=12)
    staging_pages = _topic_pages(pages, ["loan impairment provisions", "loans by stage", "stage 1", "stage 2", "stage 3", "coverage"], limit=10)
    ageing_pages = _topic_pages(pages, ["arrears", "past due", "delinquency", "not past due", "days past due"], limit=6)
    movement_pages = _topic_pages(pages, ["flow statement", "transfers from stage 1 to stage 2", "write-offs", "at 31 december 2025", "total credit impairment charge"], limit=10)

    model = _extract_model_structure("\n".join(page.text for page in model_pages) or merged_text, source_anchor)
    model.evidence = _page_snippets(model_pages, ["stage 1", "stage 2", "stage 3", "simplified approach", "lifetime expected credit losses"], limit=3) or model.evidence

    scenario = _extract_scenario_design("\n".join(page.text for page in scenario_pages) or merged_text, source_anchor)
    scenario.evidence = _page_snippets(scenario_pages, ["scenario", "base case", "upside", "downside", "severe downside", "weight"], limit=4) or scenario.evidence

    key_params = _extract_key_parameters("\n".join(page.text for page in key_param_pages) or merged_text, source_anchor)
    key_params.evidence = _page_snippets(key_param_pages, ["pd", "probability of default", "lgd", "loss given default", "ead", "exposure at default", "forward-looking"], limit=4) or key_params.evidence

    gross = None
    allowance = None
    core_table = None
    metric_basis = None

    for page in core_pages:
        gross, allowance, core_table, metric_basis = _extract_natwest_like_core(page)
        if gross is not None and allowance is not None:
            break
    if gross is None or allowance is None:
        for page in core_pages:
            gross, allowance, core_table, metric_basis = _extract_santander_like_core(page)
            if gross is not None and allowance is not None:
                break
    if gross is None or allowance is None:
        gross, allowance, core_table, metric_basis = _extract_barclays_like_core(core_pages)
    if gross is None or allowance is None:
        gross, allowance, core_table = _extract_core_metrics("\n".join(page.text for page in core_pages), _topic_tables(core_pages))

    ratio = safe_ratio(
        abs(allowance) if allowance is not None else None,
        abs(gross) if gross is not None else None,
    )
    method = "derived" if ratio is not None else None
    units = [_detect_unit(page.text) for page in core_pages if _detect_unit(page.text)]
    unit = units[0] if units else None
    company_type = _classify_company_type(company, "\n".join(page.text for page in pages[:12]))

    benchmark = CompanyBenchmark(
        company=company,
        report_url=report_url,
        report_period=report_period_from_url(report_url),
        model_structure=model,
        scenario_design=scenario,
        key_parameters=key_params,
        gross_exposure=abs(gross) if gross is not None else None,
        ecl_allowance=allowance,
        coverage_ratio=ratio,
        coverage_ratio_method=method,
        exposure_unit=unit,
        ecl_unit=unit,
        metric_basis=metric_basis,
        company_type=company_type,
        core_ecl_table=core_table,
        staging_table=_extract_staging_table(_topic_tables(staging_pages)),
        ageing_table=_extract_ageing_table(_topic_tables(ageing_pages)),
        impairment_movement_table=_extract_impairment_movement_table(_topic_tables(movement_pages)),
        source_documents=[doc.url for doc in docs],
    )

    if benchmark.coverage_ratio is None:
        benchmark.notes.append("Coverage ratio unavailable from extracted data.")
    if benchmark.metric_basis:
        benchmark.notes.append(f"Metric basis: {benchmark.metric_basis}.")
    if benchmark.company_type:
        benchmark.notes.append(f"Company type inferred as {benchmark.company_type}.")
    if benchmark.model_structure.value is None:
        benchmark.notes.append("Model structure not confidently extracted; validate manually.")
    if benchmark.core_ecl_table is None:
        benchmark.notes.append("No single reliable core ECL table was identified; values may not be directly comparable.")
    _append_stage_coverage_note(benchmark)
    _extract_ageing_analysis(benchmark)
    _extract_impairment_analysis(benchmark)
    return benchmark


def evidence_to_text(field: ExtractedField) -> str:
    snippets = [e.text for e in field.evidence if e.text]
    return " | ".join(snippets)


def keyword_density(text: str, keywords: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    lines = split_sentences(text)
    for line in lines:
        low = line.lower()
        for keyword in keywords:
            if keyword.lower() in low:
                counts[keyword] += 1
    return counts
