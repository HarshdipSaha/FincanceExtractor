from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DisclosureStatus = Literal["EXACT", "PROXY", "DERIVED", "NOT DISCLOSED"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class SourceRef(BaseModel):
    page: int | str | None = None
    table_or_section: str | None = ""
    quote: str | None = ""


class MetricValue(BaseModel):
    label: str
    value: float | str | None = None
    unit: str | None = ""
    source: SourceRef = Field(default_factory=SourceRef)
    disclosure_status: DisclosureStatus = "NOT DISCLOSED"
    confidence: Confidence = "LOW"
    note: str | None = ""


class CoreECLTable(BaseModel):
    gross_customer_receivables: MetricValue = Field(default_factory=lambda: MetricValue(label="Gross customer receivables"))
    net_receivables_before_ecl: MetricValue = Field(default_factory=lambda: MetricValue(label="Net receivables before ECL"))
    ecl_allowance: MetricValue = Field(default_factory=lambda: MetricValue(label="ECL allowance"))
    net_after_ecl: MetricValue = Field(default_factory=lambda: MetricValue(label="Net after ECL"))
    derived_coverage_ratio: MetricValue = Field(default_factory=lambda: MetricValue(label="Derived coverage ratio", unit="%"))
    notes: list[str] = Field(default_factory=list)


class StageRow(BaseModel):
    stage: Literal["Stage 1", "Stage 2", "Stage 3", "Total"]
    gross_exposure: MetricValue = Field(default_factory=lambda: MetricValue(label="Gross exposure"))
    ecl_allowance: MetricValue = Field(default_factory=lambda: MetricValue(label="ECL allowance"))
    net_exposure: MetricValue = Field(default_factory=lambda: MetricValue(label="Net exposure"))
    coverage_ratio: MetricValue = Field(default_factory=lambda: MetricValue(label="Coverage ratio", unit="%"))


class MovementRow(BaseModel):
    stage: Literal["Stage 1", "Stage 2", "Stage 3", "Total"]
    opening: MetricValue = Field(default_factory=lambda: MetricValue(label="Opening"))
    charge_release: MetricValue = Field(default_factory=lambda: MetricValue(label="Charge / release"))
    charge_offs_or_movement: MetricValue = Field(default_factory=lambda: MetricValue(label="Charge-offs / movement"))
    write_offs: MetricValue = Field(default_factory=lambda: MetricValue(label="Write-offs"))
    closing: MetricValue = Field(default_factory=lambda: MetricValue(label="Closing"))


class ModelDesignDetails(BaseModel):
    framework_design: MetricValue = Field(default_factory=lambda: MetricValue(label="IFRS 9 / ECL framework design"))
    number_of_scenarios: MetricValue = Field(default_factory=lambda: MetricValue(label="Number of scenarios"))
    scenario_names: MetricValue = Field(default_factory=lambda: MetricValue(label="Scenario names"))
    scenario_weights: MetricValue = Field(default_factory=lambda: MetricValue(label="Scenario weights"))
    sicr_stage2_design: MetricValue = Field(default_factory=lambda: MetricValue(label="SICR / Stage 2 design"))
    backstop_rules: MetricValue = Field(default_factory=lambda: MetricValue(label="Backstop rules"))
    management_adjustments: MetricValue = Field(default_factory=lambda: MetricValue(label="Management adjustments / PMAs / overlays / JAs"))
    economic_uncertainty_by_stage: MetricValue = Field(default_factory=lambda: MetricValue(label="Economic uncertainty adjustment by stage"))
    climate_overlay: MetricValue = Field(default_factory=lambda: MetricValue(label="Climate overlay / climate model treatment"))
    model_building_blocks: MetricValue = Field(default_factory=lambda: MetricValue(label="Key model building blocks"))


class SectionNote(BaseModel):
    subsection: str
    disclosure_status: DisclosureStatus
    confidence: Confidence
    note: str


def is_metric_not_disclosed(m: MetricValue | None) -> bool:
    if m is None:
        return True
    
    if m.disclosure_status == "NOT DISCLOSED":
        return True
        
    # Check if BOTH value and note are effectively empty/not disclosed
    value_missing = (m.value is None or str(m.value).strip().lower() in ["not disclosed", "not found", "n/a", "na", "none", ""])
    note_missing = (not m.note or str(m.note).strip().lower() in ["not disclosed", "not found", "n/a", "na", "none", ""])
    
    return value_missing and note_missing

def is_note_not_disclosed(note: SectionNote) -> bool:
    return note.disclosure_status == "NOT DISCLOSED" or not note.note or note.note.strip().lower() in ["not disclosed", "not found", "n/a", "na", "none", ""]

class FirmReport(BaseModel):
    firm_name: str
    business_model: str = ""
    portfolio_comparability: str = ""
    source_pdf: str = ""
    parser_used: str = ""
    core_ecl_coverage: CoreECLTable = Field(default_factory=CoreECLTable)
    staging_table: list[StageRow] = Field(default_factory=list)
    impairment_movement_table: list[MovementRow] = Field(default_factory=list)
    model_design_details: ModelDesignDetails = Field(default_factory=ModelDesignDetails)
    notes: list[SectionNote] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)

    def is_metric_hidden(self, m: MetricValue) -> bool:
        return is_metric_not_disclosed(m)

    def is_note_hidden(self, note: SectionNote) -> bool:
        return is_note_not_disclosed(note)

    @property
    def not_disclosed_factors(self) -> list[str]:
        factors = []
        
        def check_metric(m: MetricValue | None, prefix: str = ""):
            if is_metric_not_disclosed(m):
                label = f"{prefix}{m.label}" if prefix and m else (m.label if m else "Unknown")
                factors.append(label)

        # Core ECL
        check_metric(self.core_ecl_coverage.gross_customer_receivables, "Core ECL - ")
        check_metric(self.core_ecl_coverage.net_receivables_before_ecl, "Core ECL - ")
        check_metric(self.core_ecl_coverage.ecl_allowance, "Core ECL - ")
        check_metric(self.core_ecl_coverage.net_after_ecl, "Core ECL - ")
        check_metric(self.core_ecl_coverage.derived_coverage_ratio, "Core ECL - ")

        # Staging
        for row in self.staging_table:
            check_metric(row.gross_exposure, f"Staging ({row.stage}) - ")
            check_metric(row.ecl_allowance, f"Staging ({row.stage}) - ")
            check_metric(row.net_exposure, f"Staging ({row.stage}) - ")
            check_metric(row.coverage_ratio, f"Staging ({row.stage}) - ")

        # Movement
        for row in self.impairment_movement_table:
            check_metric(row.opening, f"Movement ({row.stage}) - ")
            check_metric(row.charge_release, f"Movement ({row.stage}) - ")
            check_metric(row.charge_offs_or_movement, f"Movement ({row.stage}) - ")
            check_metric(row.write_offs, f"Movement ({row.stage}) - ")
            check_metric(row.closing, f"Movement ({row.stage}) - ")

        # Model Design
        check_metric(self.model_design_details.framework_design, "Model Design - ")
        check_metric(self.model_design_details.number_of_scenarios, "Model Design - ")
        check_metric(self.model_design_details.scenario_names, "Model Design - ")
        check_metric(self.model_design_details.scenario_weights, "Model Design - ")
        check_metric(self.model_design_details.sicr_stage2_design, "Model Design - ")
        check_metric(self.model_design_details.backstop_rules, "Model Design - ")
        check_metric(self.model_design_details.management_adjustments, "Model Design - ")
        check_metric(self.model_design_details.economic_uncertainty_by_stage, "Model Design - ")
        check_metric(self.model_design_details.climate_overlay, "Model Design - ")
        check_metric(self.model_design_details.model_building_blocks, "Model Design - ")

        # Notes
        for note in self.notes:
            if is_note_not_disclosed(note):
                factors.append(f"Note - {note.subsection}")

        return list(dict.fromkeys(factors))



class BenchmarkReport(BaseModel):
    title: str = "IFRS 9 / ECL Benchmarking Report"
    firms: list[FirmReport] = Field(default_factory=list)


class DocumentExtraction(BaseModel):
    firms: list[FirmReport] = Field(default_factory=list)
