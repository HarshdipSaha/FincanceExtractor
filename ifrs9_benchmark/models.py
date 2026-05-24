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


class BenchmarkReport(BaseModel):
    title: str = "IFRS 9 / ECL Benchmarking Report"
    firms: list[FirmReport] = Field(default_factory=list)


class DocumentExtraction(BaseModel):
    firms: list[FirmReport] = Field(default_factory=list)
