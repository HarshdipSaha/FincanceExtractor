from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from groq import APIConnectionError, APIStatusError, Groq

from .config import get_groq_keys, load_local_keys
from .models import DocumentExtraction, FirmReport


SYSTEM_PROMPT = """You are an expert IFRS 9 credit risk analyst.
Extract only facts supported by the supplied annual-report page text.
Never invent missing values. If a value is absent, use null and NOT DISCLOSED.
Every populated figure or qualitative detail must cite page number and table/section title.
Map company labels transparently:
- gross carrying amount, gross exposure, loans and advances to customers, customer loans, trade receivables, and financial assets at amortised cost may be proxies for gross customer receivables.
- expected credit loss allowance, impairment allowance, loss allowance, and provision may be proxies for ECL allowance.
- PMA, overlay, management adjustment, judgemental adjustment, economic uncertainty adjustment and JA are related terms.
- For impairment movement, "income statement charge", "net remeasurement of ECL", or "charge to income statement" should map to charge_release. "Amounts written off" or "write-offs" map to write_offs. "Transfers" or "other movements" map to charge_offs_or_movement.
Use the report's original units and state them, e.g. GBP million, GBP billion, EUR million.
Derived coverage ratio = ECL allowance / gross exposure * 100 when both source figures exist.
If the annual report contains financial disclosures for multiple distinct corporate entities (e.g., Barclays Bank UK Group AND Barclays Bank UK PLC), you MUST extract and return a separate, distinct report object for EACH entity.
For Barclays Bank UK annual reports, return separate sections for Barclays Bank UK Group and Barclays Bank UK PLC when both tables are visible.
Model design is often qualitative. For qualitative fields such as framework design, scenario names, SICR design, backstops, overlays, climate treatment, PD, LGD, and EAD, put the extracted text in MetricValue.note and keep MetricValue.value null unless there is a single numeric value.
Actively search for these model-design synonyms: macroeconomic scenarios, scenario weights, probability weights, base case, baseline, upside, downside, significant increase in credit risk, SICR, 30 days past due, 90 days past due, watchlist, forbearance, post-model adjustment, management overlay, judgemental adjustment, economic uncertainty adjustment, climate-related ECL, probability of default, loss given default, exposure at default.
For retailer annual reports that do not disclose IFRS 9 Stage 1/2/3, do not force risk bands or ageing buckets into staging_table. Put them in notes as a proxy caveat and mark staging as NOT DISCLOSED.
Return strict JSON with a top-level "firms" array.
MetricValue fields are: label, value (number or null), unit, source {page, table_or_section, quote}, disclosure_status, confidence, note.
Allowed disclosure_status values: EXACT, PROXY, DERIVED, NOT DISCLOSED.
Allowed confidence values: HIGH, MEDIUM, LOW."""


class GroqExtractor:
    def __init__(self, model: str) -> None:
        load_local_keys(Path.cwd())
        self.keys = get_groq_keys(Path.cwd())
        if not self.keys:
            self.keys = [""]
        self.key_index = 0
        self.client = Groq(api_key=self.keys[self.key_index] or None)
        self.model = model

    def extract(self, pdf_name: str, context: str) -> list[FirmReport]:
        prompt = {
            "source_pdf": pdf_name,
            "json_shape": JSON_SHAPE,
            "page_text": context,
        }
        if "barclays" in pdf_name.lower():
            prompt["required_entities"] = [
                "Barclays Bank UK Group",
                "Barclays Bank UK PLC",
            ]
        elif "natwest" in pdf_name.lower():
            prompt["required_entities"] = [
                "NatWest Group"
            ]
        data = self._chat_json(prompt)
        if "firms" not in data:
            data = {"firms": [data]}
        extraction = DocumentExtraction.model_validate({"firms": [_normalize_report_item(_drop_nulls(item)) for item in data.get("firms", [])]})
        firms = extraction.firms
        for firm in firms:
            if not firm.source_pdf:
                firm.source_pdf = pdf_name

        required_entities = prompt.get("required_entities", [])
        if required_entities:
            firms = self._fill_missing_entities(pdf_name, context, firms, required_entities)
        return firms

    def _chat_json(self, prompt: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts = max(3, len(self.keys) * 3)
        for _attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(prompt)[:110000]},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                return _load_json_object(content)
            except (APIConnectionError, APIStatusError) as exc:
                last_error = exc
                if _is_request_too_large(exc) and isinstance(prompt.get("page_text"), str) and len(prompt["page_text"]) > 4000:
                    next_len = max(4000, len(prompt["page_text"]) // 2)
                    prompt = {**prompt, "page_text": prompt["page_text"][:next_len]}
                    continue
                self._rotate_key()
        if last_error:
            raise last_error
        raise RuntimeError("Groq extraction failed without a response.")

    def _rotate_key(self) -> None:
        if len(self.keys) <= 1:
            return
        self.key_index = (self.key_index + 1) % len(self.keys)
        self.client = Groq(api_key=self.keys[self.key_index])

    def _fill_missing_entities(
        self,
        pdf_name: str,
        context: str,
        firms: list[FirmReport],
        required_entities: list[str],
    ) -> list[FirmReport]:
        present = {firm.firm_name.lower().strip() for firm in firms}
        completed = list(firms)
        for entity in required_entities:
            existing_index = _find_entity_index(completed, entity)
            if existing_index is not None and _has_core_values(completed[existing_index]):
                continue
            entity_prompt = {
                "source_pdf": pdf_name,
                "required_entity": entity,
                "instruction": f"Extract ONLY {entity}. Return exactly one item in the top-level firms array.",
                "json_shape": JSON_SHAPE,
                "page_text": context,
            }
            data = self._chat_json(entity_prompt)
            if "firms" not in data:
                data = {"firms": [data]}
            for item in data.get("firms", [])[:1]:
                firm = FirmReport.model_validate(_normalize_report_item(_drop_nulls(item)))
                firm.firm_name = entity
                firm.source_pdf = pdf_name
                if existing_index is None:
                    completed.append(firm)
                else:
                    completed[existing_index] = firm
                present.add(entity.lower())
        return completed


def _load_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _is_request_too_large(exc: Exception) -> bool:
    text = str(exc).lower()
    return "request too large" in text or "tpm" in text or "413" in text


def _drop_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_nulls(item) for item in value if item is not None]
    return value


METRIC_KEYS = {
    "gross_customer_receivables",
    "net_receivables_before_ecl",
    "ecl_allowance",
    "net_after_ecl",
    "derived_coverage_ratio",
    "gross_exposure",
    "net_exposure",
    "coverage_ratio",
    "opening",
    "charge_release",
    "charge_offs_or_movement",
    "write_offs",
    "closing",
    "framework_design",
    "number_of_scenarios",
    "scenario_names",
    "scenario_weights",
    "sicr_stage2_design",
    "backstop_rules",
    "management_adjustments",
    "economic_uncertainty_by_stage",
    "climate_overlay",
    "model_building_blocks",
}


def _normalize_report_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed_stages = {"Stage 1", "Stage 2", "Stage 3", "Total"}

    def normalize(value: Any, key: str | None = None, path: tuple[str, ...] = ()) -> Any:
        if key in METRIC_KEYS and not isinstance(value, dict):
            return _metric_from_scalar(key, value)
        if key == "notes" and isinstance(value, list):
            if path == ("notes",):
                return [_note_from_scalar(child_value) if not isinstance(child_value, dict) else normalize(child_value, path=path) for child_value in value]
            return [str(child_value.get("note", child_value)) if isinstance(child_value, dict) else str(child_value) for child_value in value]
        if isinstance(value, dict):
            if path == ("notes",):
                value.setdefault("subsection", "General")
                value.setdefault("disclosure_status", "PROXY")
                value.setdefault("confidence", "LOW")
                if "note" not in value and "text" in value:
                    value["note"] = str(value.pop("text"))
            return {child_key: normalize(child_value, child_key, path + (child_key,)) for child_key, child_value in value.items()}
        if isinstance(value, list):
            normalized_items = [normalize(child_value, path=path) for child_value in value]
            if path and path[-1] in {"staging_table", "impairment_movement_table"}:
                return [
                    child_value
                    for child_value in normalized_items
                    if isinstance(child_value, dict) and child_value.get("stage") in allowed_stages
                ]
            return normalized_items
        return value

    return normalize(item)


def _metric_from_scalar(key: str, value: Any) -> dict[str, Any]:
    label = key.replace("_", " ").title()
    numeric_value = value if isinstance(value, (int, float)) else None
    note = "" if numeric_value is not None else str(value)
    return {
        "label": label,
        "value": numeric_value,
        "unit": "",
        "source": {},
        "disclosure_status": "EXACT" if value not in (None, "") else "NOT DISCLOSED",
        "confidence": "LOW",
        "note": note,
    }


def _note_from_scalar(value: Any) -> dict[str, str]:
    return {
        "subsection": "General",
        "disclosure_status": "PROXY",
        "confidence": "LOW",
        "note": str(value),
    }


def _find_entity_index(firms: list[FirmReport], entity: str) -> int | None:
    entity_lower = entity.lower()
    for index, firm in enumerate(firms):
        if entity_lower == firm.firm_name.lower().strip():
            return index
    return None


def _has_core_values(firm: FirmReport) -> bool:
    core = firm.core_ecl_coverage
    return core.gross_customer_receivables.value is not None and core.ecl_allowance.value is not None


JSON_SHAPE = {
    "firms": [
        {
            "firm_name": "string",
            "business_model": "string",
            "portfolio_comparability": "string",
            "source_pdf": "string",
            "core_ecl_coverage": {
                "gross_customer_receivables": "MetricValue",
                "net_receivables_before_ecl": "MetricValue",
                "ecl_allowance": "MetricValue",
                "net_after_ecl": "MetricValue",
                "derived_coverage_ratio": "MetricValue",
                "notes": ["string"],
            },
            "staging_table": [
                {
                    "stage": "Stage 1 | Stage 2 | Stage 3 | Total",
                    "gross_exposure": "MetricValue",
                    "ecl_allowance": "MetricValue",
                    "net_exposure": "MetricValue",
                    "coverage_ratio": "MetricValue",
                }
            ],
            "impairment_movement_table": [
                {
                    "stage": "Stage 1 | Stage 2 | Stage 3 | Total",
                    "opening": "MetricValue",
                    "charge_release": "MetricValue",
                    "charge_offs_or_movement": "MetricValue",
                    "write_offs": "MetricValue",
                    "closing": "MetricValue",
                }
            ],
            "model_design_details": {
                "framework_design": "MetricValue",
                "number_of_scenarios": "MetricValue",
                "scenario_names": "MetricValue",
                "scenario_weights": "MetricValue",
                "sicr_stage2_design": "MetricValue",
                "backstop_rules": "MetricValue",
                "management_adjustments": "MetricValue",
                "economic_uncertainty_by_stage": "MetricValue",
                "climate_overlay": "MetricValue",
                "model_building_blocks": "MetricValue",
            },
            "notes": [
                {
                    "subsection": "string",
                    "disclosure_status": "EXACT | PROXY | DERIVED | NOT DISCLOSED",
                    "confidence": "HIGH | MEDIUM | LOW",
                    "note": "string",
                }
            ],
        }
    ]
}
