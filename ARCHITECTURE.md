# Architecture Guide - From Business Concept to Code

This document explains how each Python file in this project implements the business concepts from [CONCEPT.md](CONCEPT.md). Written for non-technical readers transitioning to tech.

---

## How to Read This Guide

Think of this tool like a **factory assembly line**:

```
Raw PDF Reports → [Various Machines] → Structured Data → Comparison Report
```

Each Python file is a **machine** in this factory. Each machine has a specific job.

---

## File-by-File Breakdown

### 1. `models.py` - The Blueprint Definitions

**Business Concept:** Structured Data Models (from CONCEPT.md, Section 4)

**What It Does:**
Defines the **shapes** of data we work with - like creating blank forms before filling them out.

**The Forms Defined:**

| Form Name | What It Holds | Real-World Analogy |
|-----------|---------------|-------------------|
| `Evidence` | A quote + where it came from | A photocited excerpt with page number |
| `ExtractedField` | A value + its evidence | A filled form field + source documents |
| `TableData` | A table's rows/columns | Excel spreadsheet data |
| `FilingLink` | Company report metadata | Library catalog card |
| `SourceDocument` | One report's content | One annual report PDF |
| `CompanyBenchmark` | **All data about one company** | Complete dossier on one company |
| `AgeingBucket` | One delinquency bucket | One row in ageing table |
| `StageMovement` | One stage's impairment flow | One row in movement table |

**Why Separate This?**
Imagine if every department in a company used different forms. Chaos! By defining forms upfront, every other file knows exactly what data to expect.

**Code Pattern:**
```python
@dataclass
class AgeingBucket:
    bucket_name: str      # "Not Past Due", "0-60 Days", etc.
    gross_amount: float   # How much money owed in this bucket
    allowance_amount: float  # How much set aside for losses
    coverage_ratio: float # allowance ÷ gross
```

---

### 2. `fetch.py` - The Document Collector

**Business Concept:** Layer 1 - Document Loading (from CONCEPT.md, Section 2)

**What It Does:**
Goes out to the internet and **fetches** company reports.

**Key Functions:**

| Function | Job | Analogy |
|----------|-----|---------|
| `HttpClient.get_text()` | Downloads web pages | Web browser |
| `HttpClient.get_bytes()` | Downloads PDF files | File downloader |
| `discover_company_filings()` | Finds reports by company name | Library catalog search |
| `extract_filing_links()` | Extracts links from HTML pages | Link scraper |
| `select_latest_comparable()` | Matches same-year reports | Pairing socks by year |
| `extract_pdf_links()` | Finds PDF download links | PDF hunter |

**How It Works:**

```
User says: "Get Next plc report"
     ↓
HttpClient searches financialreports.eu
     ↓
Finds: "Next plc Annual Report 2026"
     ↓
Downloads the PDF
     ↓
Passes to next machine
```

**Technical Approach:**
- Uses `requests` library (like a headless web browser)
- Uses `BeautifulSoup` to parse HTML (reads web page structure)
- Regex patterns to identify report URLs

---

### 3. `parse.py` - The Document Reader

**Business Concept:** Layer 1 - PDF/HTML Parsing (from CONCEPT.md, Section 2)

**What It Does:**
Opens PDF files and extracts **text + tables** into a format Python can work with.

**Key Functions:**

| Function | Job |
|----------|-----|
| `load_document()` | Figures out if URL is PDF or HTML, then parses it |
| `parse_pdf()` | Uses `pdfplumber` to read PDF text + tables |
| `parse_html()` | Uses `BeautifulSoup` to read HTML text + tables |
| `report_period_from_url()` | Extracts year from URL |

**How PDF Parsing Works:**

```
PDF File (binary)
     ↓
pdfplumber library
     ↓
Text: "Gross receivables: £254.9m"
Tables: [[row1], [row2], ...]
     ↓
SourceDocument object
```

**Why Separate from `fetch.py`?**
Fetching = downloading. Parsing = reading. Different jobs, different files.

---

### 4. `utils.py` - The Helper Tools

**Business Concept:** Supporting utilities for all layers

**What It Does:**
Small helper functions used by other files. Think of these as **utility knives**.

**Key Functions:**

| Function | What It Does | Example |
|----------|--------------|---------|
| `parse_number()` | Converts "(254.9)" to -254.9 | Accounting format → Python number |
| `safe_ratio()` | Divides safely (handles zero) | 10/100 → 0.1, 10/0 → None |
| `fmt_number()` | Formats 254.9 as "254.9" | Python → Report format |
| `fmt_percent()` | Formats 0.287 as "28.7%" | Python → Report format |
| `contains_any()` | Checks if text has any keyword | "loan" in "bad loan" → True |
| `first_number()` | Extracts first number from text | "£254.9m" → 254.9 |
| `normalize_space()` | Cleans up whitespace | "  hello   world " → "hello world" |
| `split_sentences()` | Breaks text into sentences | Long text → [sentence1, sentence2, ...] |
| `best_sentences()` | Finds sentences with keywords | Finds relevant quotes |

**Why These Matter:**
Without these, every file would duplicate the same code. DRY principle: **Don't Repeat Yourself**.

---

### 5. `extract.py` - The Data Extraction Engine

**Business Concept:** Layers 2, 3, 4 - Metric + Table + Structured Extraction (from CONCEPT.md, Section 2)

**What It Does:**
The **brain** of the operation. Finds and extracts all the data from parsed documents.

**Extraction Flow:**

```
Parsed Text + Tables
     ↓
_extract_core_metrics() → Gross: 254.9, Allowance: -73.2
_extract_model_structure() → "3-stage IFRS 9 model"
_extract_scenario_design() → "4 scenarios: 55/10/30/5"
_extract_staging_table() → Table object
_extract_ageing_table() → Table object
_extract_impairment_movement_table() → Table object
     ↓
_parse_ageing_buckets() → [AgeingBucket, AgeingBucket, ...]
_parse_stage_movements() → [StageMovement, StageMovement, ...]
     ↓
CompanyBenchmark (complete)
```

**Key Functions by Business Purpose:**

| Function | Business Question Answered |
|----------|---------------------------|
| `_extract_core_metrics()` | How much exposure? How much provision? |
| `_extract_model_structure()` | Simplified or 3-stage model? |
| `_extract_scenario_design()` | What scenarios? What weights? |
| `_extract_key_parameters()` | PD/LGD/EAD disclosed? |
| `_pick_best_table()` | Which table is the right one? |
| `_parse_ageing_buckets()` | What % is 120+ days overdue? |
| `_parse_stage_movements()` | How much moved between stages? |

**How Table Detection Works (Keyword Scoring):**

```python
# For each table, count keyword matches:
Table 1: ["revenue", "profit"] → 0 matches (skip)
Table 2: ["Stage 1", "Stage 2", "gross", "opening"] → 4 matches ✓
Table 3: ["Stage 1", "gross"] → 2 matches

Winner: Table 2 (highest score)
```

**Why This File Is Largest:**
Most business logic lives here. Each extraction function handles different company formats, edge cases, and fallback strategies.

---

### 6. `report.py` - The Report Generator

**Business Concept:** Report Generation Philosophy (from CONCEPT.md, Section 5)

**What It Does:**
Takes extracted data and creates **readable output** (Markdown + JSON).

**Two Outputs:**

| Output | Purpose | Function |
|--------|---------|----------|
| Markdown | Human-readable comparison | `build_markdown_report()` |
| JSON | Machine-readable data | `build_json_report()` |

**Markdown Report Structure (Generated Sections):**

```
1. Header: "IFRS 9 Benchmarking Report (Company A vs Company B vs ...)"
2. Source reports: List of URLs
3. Core ECL table: Gross, Allowance, Coverage side-by-side
4. Model design table: Structure, Scenarios, Parameters
5. Ageing analysis: Delinquency buckets
6. Impairment movements: Stage flows
7. Evidence excerpts: Source quotes
8. Raw tables: Extracted tables for verification
9. Analyst notes: Auto-generated insights
```

**How Dynamic Tables Work:**

```python
# Old way (2 companies hardcoded):
"| Metric | Next | Frasers |"

# New way (N companies):
header = "| Metric |" + " | ".join(company.name for company in companies) + " |"
# Result: "| Metric | Next | Frasers | Marks & Spencer | JD Sports |"
```

**Why JSON Too?**
- Markdown = for reading in browser
- JSON = for importing into Excel, PowerBI, Python analysis

---

### 7. `cli.py` - The User Interface

**Business Concept:** URL Flexibility (from CONCEPT.md, Section 6, Decision 1)

**What It Does:**
The **command-line interface** - how users interact with the tool.

**User Input:**
```bash
python -m ifrs9_benchmark --companies "Next plc=https://url.pdf,Frasers=https://url.pdf"
```

**What Happens:**

```
cli.py receives command
     ↓
Parses company names + URLs
     ↓
Creates HttpClient
     ↓
For each company:
    - Calls extract_company_benchmark()
    - Collects CompanyBenchmark
     ↓
Calls build_markdown_report(companies)
Calls build_json_report(companies)
     ↓
Writes files to disk
     ↓
Prints summary to console
```

**Key Functions:**

| Function | Job |
|----------|-----|
| `_parse_company_urls()` | Splits "Name=url,Name2=url2" into list |
| `_resolve_urls()` | Auto-discovers URLs if not provided |
| `build_parser()` | Defines command-line arguments |
| `main()` | Orchestrates the entire run |

**Why Separate from `report.py`?**
`cli.py` = user interaction. `report.py` = output generation. Different concerns.

---

### 8. `__main__.py` - The Entry Point

**What It Does:**
Makes the package runnable with `python -m ifrs9_benchmark`.

**Code:**
```python
from .cli import main

if __name__ == "__main__":
    main()
```

**Why This Exists:**
Python convention. Without this file, you'd need to run `python ifrs9_benchmark/cli.py`. With it, you run `python -m ifrs9_benchmark`.

---

### 9. `__init__.py` - The Package Marker

**What It Does:**
Tells Python "this folder is a package". Also defines version.

**Code:**
```python
"""IFRS 9 benchmarking package."""
__version__ = "0.1.0"
```

---

### 10. `test_extract.py` - The Quality Assurance

**Business Concept:** Testing extraction accuracy

**What It Does:**
Automated tests to ensure extraction functions work correctly.

**Test Types:**

| Test | What It Checks |
|------|----------------|
| `test_parse_number_parentheses` | "(254.9)" → -254.9 |
| `test_safe_ratio` | 10/100 → 0.1 (not crash) |
| `test_extract_model_structure_three_stage` | Finds "3-stage" in text |
| `test_extract_scenario_weights` | Extracts "45/5/35/15" |
| `test_parse_ageing_buckets_basic` | Parses bucket table correctly |
| `test_parse_stage_movements` | Parses stage flows correctly |

**Why Tests Matter:**
If extraction breaks after a code change, tests catch it before bad data goes to users.

---

## How Data Flows Through the System

### Complete Journey of One Number

Let's trace how **"Frasers Group: £254.9m gross exposure"** travels through the system:

```
Step 1: fetch.py
  - Downloads Frasers annual report PDF from URL

Step 2: parse.py
  - Opens PDF, finds page with "trade receivables with a gross value of £254.9"
  - Extracts as text + table row

Step 3: extract.py (_extract_core_metrics)
  - Scans all tables for "gross" + "receivable" keywords
  - Finds table row: ["trade receivables with a gross value of £", "254.9"]
  - Calls parse_number("254.9") → 254.9
  - Stores in CompanyBenchmark.gross_exposure = 254.9

Step 4: report.py (build_markdown_report)
  - Reads company.gross_exposure
  - Calls fmt_number(254.9) → "254.9"
  - Inserts into markdown table cell

Step 5: cli.py
  - Writes markdown to ifrs9_benchmark_report.md
  - Writes JSON to ifrs9_benchmark_report.json

Final Output (Markdown):
| Metric | Frasers Group |
|--------|---------------|
| Gross exposure | 254.9 |
```

---

## Mapping Concepts to Files

| Concept (CONCEPT.md) | Implementation File(s) |
|---------------------|------------------------|
| Multi-Firm Architecture | `cli.py`, `report.py` (dynamic N-company) |
| Layered Extraction | `fetch.py` → `parse.py` → `extract.py` |
| Table Detection (Scoring) | `extract.py` (`_pick_best_table`) |
| Structured Data Models | `models.py` (`AgeingBucket`, `StageMovement`) |
| Report Generation | `report.py` (Markdown + JSON) |
| URL Flexibility | `cli.py` (`--companies` flag) |
| Pattern-Based Extraction | `extract.py` (regex patterns) |
| Evidence Tracking | `models.py` (`Evidence` class) |
| Fallback Logic | `extract.py` (multiple strategies) |

---

## Key Design Patterns Used

### 1. Dataclasses (models.py)
```python
@dataclass
class CompanyBenchmark:
    company: str
    gross_exposure: float | None
    # ... etc
```
**Why:** Clean, readable data containers. Auto-generates `__init__`, `__repr__`.

### 2. Layered Architecture (fetch → parse → extract → report)
**Why:** Each layer has one job. Easy to test, easy to replace.

### 3. Fallback Strategy (extract.py)
```python
# Try table first
if table:
    value = parse_table(table)
# Fall back to text patterns
else:
    value = extract_from_text(text, patterns)
# Default to None if nothing works
if value is None:
    notes.append("Not found")
```
**Why:** Graceful degradation. Tool never crashes on missing data.

### 4. Keyword Scoring (_pick_best_table)
```python
score = sum(1 for keyword in keywords if keyword in table_text)
```
**Why:** Flexible matching. Works even if terminology varies.

---

## Glossary for Non-Technical Readers

| Term | Meaning |
|------|---------|
| **Module** | One `.py` file |
| **Package** | A folder of modules (with `__init__.py`) |
| **Function** | A reusable piece of code (does one job) |
| **Class** | A blueprint for creating objects |
| **Dataclass** | A class designed to hold data |
| **Regex** | Pattern matching for text (e.g., find all numbers) |
| **Parse** | Read and understand structure |
| **Extract** | Pull out specific data |
| **Serialize** | Convert to JSON/text for storage |
| **Import** | Use code from another file |
| **Instance** | One specific object created from a class |

---

## Summary: The Factory Analogy

```
┌─────────────────────────────────────────────────────────────┐
│                    IFRS 9 EXTRACTION FACTORY                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Raw Materials (PDF URLs)                                   │
│       ↓                                                     │
│  ┌─────────────┐                                            │
│  │ fetch.py    │  ← The Procurement Department              │
│  │ (collects)  │     Goes out, gets raw materials            │
│  └─────────────┘                                            │
│       ↓                                                     │
│  ┌─────────────┐                                            │
│  │ parse.py    │  ← The Unpacking Department                │
│  │ (reads)     │     Opens boxes, lays out contents          │
│  └─────────────┘                                            │
│       ↓                                                     │
│  ┌─────────────┐                                            │
│  │ extract.py  │  ← The Assembly Department                 │
│  │ (finds)     │     Finds valuable parts, assembles them    │
│  └─────────────┘                                            │
│       ↓                                                     │
│  ┌─────────────┐                                            │
│  │ models.py   │  ← The Blueprint Department                │
│  │ (defines)   │     Defines what each part looks like       │
│  └─────────────┘                                            │
│       ↓                                                     │
│  ┌─────────────┐                                            │
│  │ report.py   │  ← The Packaging Department                │
│  │ (formats)   │     Packages for delivery (MD/JSON)         │
│  └─────────────┘                                            │
│       ↓                                                     │
│  ┌─────────────┐                                            │
│  │ cli.py      │  ← The Shipping Department                 │
│  │ (delivers)  │     Hands package to customer               │
│  └─────────────┘                                            │
│       ↓                                                     │
│  Finished Product (Comparison Report)                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Each file has **one clear responsibility**. Together, they transform raw PDFs into structured, comparable data.
