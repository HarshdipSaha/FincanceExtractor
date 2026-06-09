# IFRS 9 Benchmarking Tool - Concept & Implementation Overview

## What Problem Does This Solve?

### The Business Context

Under **IFRS 9** (International Financial Reporting Standard 9), companies must calculate and disclose their **Expected Credit Losses (ECL)** - essentially, how much money they expect to lose from customers who don't pay their debts.

This sounds straightforward, but there's a catch: **companies can choose different approaches**:

1. **Simplified Approach** - Always calculate lifetime expected losses (more conservative)
2. **3-Stage Model** - Different calculations based on credit risk stage:
   - Stage 1: Performing loans → 12-month ECL
   - Stage 2: Significant credit deterioration → Lifetime ECL
   - Stage 3: Credit-impaired (default) → Lifetime ECL + interest on net amount

### Why Benchmarking Matters

Analysts, investors, and regulators need to compare companies because:

| Question | What It Reveals |
|----------|-----------------|
| **Coverage ratio differs** | Is one company more conservative? Or hiding losses? |
| **Model structure differs** | Timing of provisions varies significantly |
| **Scenario weights differ** | How pessimistic/optimistic is management? |
| **Ageing profile differs** | What % of customers are seriously delinquent? |

### The Gap This Tool Fills

Before this tool, analysts had to:
1. Manually download each company's annual report (100-300 page PDFs)
2. Search for relevant tables (credit risk, ECL, impairment)
3. Extract numbers manually into Excel
4. Try to compare apples-to-oranges (different terminology, formats)

This tool **automates extraction and normalizes comparison** across multiple firms.

---

## Core Concepts

### 1. Multi-Firm Architecture

**Old approach**: Hardcoded for exactly 2 companies (Next vs Frasers)

**New approach**: Dynamic N-company comparison

```
Input: List of (Company Name, Report URL) pairs
       ↓
Parallel extraction for each company
       ↓
Unified data model per company
       ↓
Dynamic table generation for N columns
```

**Why this matters**: Analysts can now compare 3, 4, or 10 companies simultaneously - essential for peer group analysis.

---

### 2. Data Extraction Pipeline

The tool follows a **layered extraction strategy**:

```
Layer 1: Document Loading
├── PDF parsing (text + tables)
├── HTML parsing (if web report)
└── Merge all content

Layer 2: Metric Extraction
├── Core metrics (gross exposure, ECL allowance)
├── Model structure (simplified vs 3-stage)
├── Scenario design (names + weights)
└── Key parameters (PD, LGD, EAD disclosure)

Layer 3: Table Extraction
├── Staging table (by stage columns/rows)
├── Ageing table (by delinquency buckets)
└── Movement table (opening → closing)

Layer 4: Structured Analysis
├── Parse ageing buckets → coverage per bucket
├── Parse stage movements → write-off analysis
└── Calculate derived metrics (120+ DPD %)
```

**Why layered?** Each layer has fallback logic. If Layer 3 table extraction fails, Layer 2 text patterns might still find the numbers.

---

### 3. Table Detection Strategy

The tool doesn't know where tables are in advance. It uses **keyword scoring**:

**For Ageing Tables:**
- Look for: "past due", "not past due", "0-60", "60-120", "120+", "dpd", "ageing", "delinquency"
- Score tables by how many keywords appear
- Pick the highest-scoring table

**For Staging Tables:**
- Look for: "Stage 1", "Stage 2", "Stage 3" + "gross", "allowance", "opening", "closing"
- Score tables by keyword matches
- Pick the highest-scoring table

**For Movement Tables:**
- Look for: "opening", "charge", "write-off", "closing", "stage", "movement"
- Same scoring approach

**Why scoring?** Companies use different terminology. Scoring finds the "best match" even if exact keywords vary.

---

### 4. Structured Data Models

The tool introduces **domain-specific data structures**:

**AgeingBucket:**
- bucket_name: "Not Past Due", "0-60 Days", "60-120 Days", "120+ Days"
- gross_amount: Total receivables in bucket
- allowance_amount: ECL reserved for that bucket
- coverage_ratio: Calculated as allowance ÷ gross

**StageMovement:**
- stage: "Stage 1", "Stage 2", "Stage 3"
- opening: Balance at period start
- charge: New impairment charged
- write_offs: Amounts written off (reduces allowance)
- closing: Balance at period end

**Why structured?** Enables:
- Cross-company comparison of specific buckets
- Trend analysis (opening → closing)
- Ratio calculations (Stage 3 coverage %)

---

### 5. Report Generation Philosophy

**Markdown Report Structure:**

1. **Executive Summary** - Core metrics side-by-side
2. **Model Design** - How companies calculate ECL
3. **Ageing Analysis** - Delinquency breakdown
4. **Impairment Movements** - Stage-level flows
5. **Evidence** - Source text excerpts (audit trail)
6. **Raw Tables** - Extracted tables for verification
7. **Analyst Notes** - Auto-generated insights

**JSON Report:**
- Machine-readable version of all extracted data
- Enables downstream Excel/PowerBI analysis

**Why both?** Markdown for reading; JSON for processing.

---

## Implementation Design Decisions

### Decision 1: URL Flexibility

**Problem**: Some users have direct PDF links; others want auto-discovery.

**Solution**: `--companies` accepts:
- `Name=URL` → Use explicit URL
- `Name` only → Auto-discover from financialreports.eu

**Trade-off**: Auto-discovery depends on external site structure; explicit URLs are more reliable.

---

### Decision 2: Pattern-Based Extraction

**Problem**: Every company uses different table formats.

**Solution**: Regex patterns + keyword scoring instead of fixed positions.

**Trade-off**: More robust to format changes, but may miss edge cases.

---

### Decision 3: Evidence Tracking

**Problem**: Extracted numbers need audit trails.

**Solution**: Every extracted field stores:
- The value
- Source text snippets
- Source URL

**Trade-off**: More memory usage, but enables verification.

---

### Decision 4: Fallback Logic

**Problem**: Not all tables parse cleanly.

**Solution**: Multiple extraction strategies:
1. Try structured table parsing first
2. Fall back to regex text patterns
3. Store "n/a" if nothing works (don't crash)

**Trade-off**: Complex code, but graceful degradation.

---

## Key Metrics Explained

### Coverage Ratio

```
Coverage Ratio = ECL Allowance ÷ Gross Receivables
```

**Interpretation**:
- 10% = Company expects to lose 10% of what customers owe
- Higher = More conservative OR riskier customer base
- Lower = Less conservative OR safer customer base

### 120+ DPD Percentage

```
% 120+ DPD = (Receivables >120 days past due) ÷ Total Receivables
```

**Interpretation**:
- Measures severity of delinquency
- >10% suggests significant credit stress
- Aligns with Stage 3 (default) classification

### Stage 3 Coverage

```
Stage 3 Coverage = Stage 3 Allowance ÷ Stage 3 Gross
```

**Interpretation**:
- 80%+ = Typical for defaulted loans (most will be written off)
- <50% = Potentially under-provisioned

---

## How To Extend This Tool

### Adding New Metrics

1. Add field to `CompanyBenchmark` dataclass
2. Add extraction function in `extract.py`
3. Add to markdown/JSON report builders

### Supporting New Table Types

1. Add detection keywords to `_pick_best_table`
2. Add parsing function (like `_parse_ageing_buckets`)
3. Call from `extract_company_benchmark`

### Adding New Companies

No code changes needed - just pass new URLs via CLI:
```bash
--companies "New Co=https://url.pdf,Existing Co=https://url.pdf"
```

---

## Limitations & Assumptions

| Limitation | Mitigation |
|------------|------------|
| PDF parsing depends on text layer | Scanned PDFs won't work |
| Keyword scoring may pick wrong table | Evidence excerpts allow manual verification |
| Auto-discovery depends on external site | Explicit URLs always work |
| No support for interim reports | Filter by `--candidate-slugs` |

---

## Summary

This tool transforms **manual, error-prone analyst work** into **automated, reproducible extraction**:

- **Before**: 2-3 hours per company to extract + normalize
- **After**: 30 seconds per company, consistent format

The key innovations:
1. **Multi-firm support** - Compare any number of peers
2. **Layered extraction** - Robust to format variations
3. **Structured outputs** - Enables quantitative analysis
4. **Evidence tracking** - Audit trail for every number
