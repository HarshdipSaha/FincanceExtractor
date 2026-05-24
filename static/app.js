const form = document.querySelector("#report-form");
const filesInput = document.querySelector("#files");
const fileList = document.querySelector("#file-list");
const statusBox = document.querySelector("#status");
const resultsBox = document.querySelector("#results");
const submit = document.querySelector("#submit");
const themeToggle = document.querySelector("#theme-toggle");
const heroFileCount = document.querySelector("#hero-file-count");
const heroFilePreview = document.querySelector("#hero-file-preview");
const reportBrowser = document.querySelector("#report-browser");

const sections = [
  ["core", "Core ECL"],
  ["staging", "Staging"],
  ["movement", "Impairment"],
  ["model", "Model method"],
  ["notes", "Notes"]
];

const savedTheme = localStorage.getItem("ifrs9-theme");
if (savedTheme === "dark") document.body.classList.add("dark");

themeToggle.addEventListener("click", () => {
  document.body.classList.toggle("dark");
  localStorage.setItem("ifrs9-theme", document.body.classList.contains("dark") ? "dark" : "light");
});

filesInput.addEventListener("change", () => {
  renderSelectedFiles();
});

function renderSelectedFiles() {
  const files = Array.from(filesInput.files || []);
  fileList.innerHTML = "";
  heroFilePreview.innerHTML = "";
  heroFileCount.textContent = files.length ? `${files.length} PDF${files.length === 1 ? "" : "s"} selected` : "No PDFs selected";

  if (files.length > 15) {
    statusBox.hidden = false;
    statusBox.innerHTML = '<span class="warn">Select no more than 15 PDFs.</span>';
    submit.disabled = true;
    return;
  }

  submit.disabled = false;
  if (!files.length) {
    heroFilePreview.innerHTML = "<p>Your uploaded annual reports will appear here before extraction.</p>";
    return;
  }

  for (const file of files) {
    const size = `${(file.size / 1048576).toFixed(2)} MB`;
    const item = document.createElement("div");
    item.className = "file-item";
    item.innerHTML = `<strong>${escapeHtml(file.name)}</strong><span>${size} · PDF annual report</span>`;
    fileList.appendChild(item);

    const heroItem = document.createElement("div");
    heroItem.className = "hero-file-item";
    heroItem.innerHTML = `<strong>${escapeHtml(file.name)}</strong><span>${size}</span>`;
    heroFilePreview.appendChild(heroItem);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = Array.from(filesInput.files || []);
  if (!files.length) return;
  if (files.length > 15) {
    statusBox.hidden = false;
    statusBox.innerHTML = '<span class="warn">Select no more than 15 PDFs.</span>';
    return;
  }

  submit.disabled = true;
  resultsBox.hidden = true;
  reportBrowser.hidden = true;
  statusBox.hidden = false;
  statusBox.innerHTML = "<strong>Reading PDFs and extracting IFRS 9 disclosures...</strong><br>The output will cite pages, table/section names, confidence, and disclosure status.";

  const data = new FormData(form);
  try {
    const response = await fetch("/api/reports", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Report generation failed.");
    const failures = payload.summary.failures?.length || 0;
    statusBox.innerHTML = `<strong>Report generated.</strong><br>${payload.summary.firm_count} firm sections. Validation warnings: ${payload.summary.warnings}. Failed PDFs: ${failures}.`;
    resultsBox.hidden = false;
    resultsBox.innerHTML = `
      <div><strong>Detected firms:</strong> ${payload.summary.firms.map(escapeHtml).join(", ")}</div>
      <div class="actions">
        <a href="${payload.pdf_url}" target="_blank">Open PDF report</a>
        <a href="${payload.html_url}" target="_blank">Open HTML report</a>
        <a href="${payload.json_url}" target="_blank">Open structured JSON</a>
      </div>`;

    const jsonResponse = await fetch(payload.json_url);
    const report = await jsonResponse.json();
    renderReportBrowser(report);
  } catch (error) {
    statusBox.innerHTML = `<span class="warn">${escapeHtml(error.message)}</span>`;
  } finally {
    submit.disabled = false;
  }
});

function renderReportBrowser(report) {
  const firms = report.firms || [];
  if (!firms.length) return;

  reportBrowser.hidden = false;
  reportBrowser.innerHTML = `
    <div class="section-heading">
      <div>
        <span class="eyebrow">Review extracted firms</span>
        <h2>Benchmark sections</h2>
      </div>
    </div>
    <div class="firm-tabs"></div>
    <div class="subsection-tabs"></div>
    <div class="section-panel"></div>`;

  const firmTabs = reportBrowser.querySelector(".firm-tabs");
  const subsectionTabs = reportBrowser.querySelector(".subsection-tabs");
  const sectionPanel = reportBrowser.querySelector(".section-panel");
  let activeFirmIndex = 0;
  let activeSection = "core";

  function draw() {
    firmTabs.innerHTML = firms.map((firm, index) => `
      <button class="tab-button ${index === activeFirmIndex ? "active" : ""}" data-firm="${index}">
        ${escapeHtml(firm.firm_name || `Firm ${index + 1}`)}
      </button>`).join("");

    subsectionTabs.innerHTML = sections.map(([key, label]) => `
      <button class="sub-button ${key === activeSection ? "active" : ""}" data-section="${key}">
        ${label}
      </button>`).join("");

    sectionPanel.innerHTML = renderSection(firms[activeFirmIndex], activeSection);
  }

  firmTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-firm]");
    if (!button) return;
    activeFirmIndex = Number(button.dataset.firm);
    activeSection = "core";
    draw();
  });

  subsectionTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-section]");
    if (!button) return;
    activeSection = button.dataset.section;
    draw();
  });

  draw();
  reportBrowser.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSection(firm, section) {
  if (section === "core") return renderCore(firm);
  if (section === "staging") return renderRows("Staging table", firm.staging_table, ["stage", "gross_exposure", "ecl_allowance", "net_exposure", "coverage_ratio"]);
  if (section === "movement") return renderRows("Impairment movement", firm.impairment_movement_table, ["stage", "opening", "charge_release", "charge_offs_or_movement", "write_offs", "closing"]);
  if (section === "model") return renderModel(firm);
  return renderNotes(firm);
}

function renderCore(firm) {
  const core = firm.core_ecl_coverage || {};
  const rows = [
    core.gross_customer_receivables,
    core.net_receivables_before_ecl,
    core.ecl_allowance,
    core.net_after_ecl,
    core.derived_coverage_ratio
  ].filter(Boolean);
  return `
    <h3>${escapeHtml(firm.firm_name || "Firm")} · Core ECL / coverage</h3>
    ${renderMetricTable(rows)}
    ${renderCoreNotes(core.notes || [])}`;
}

function renderRows(title, rows = [], keys = []) {
  if (!rows.length) return `<h3>${title}</h3><p class="empty">Not disclosed or not extracted with sufficient confidence.</p>`;
  return `
    <h3>${title}</h3>
    <div class="table-scroll">
      <table>
        <tr>${keys.map(key => `<th>${labelize(key)}</th>`).join("")}</tr>
        ${rows.map(row => `<tr>${keys.map(key => `<td>${renderCell(row[key])}</td>`).join("")}</tr>`).join("")}
      </table>
    </div>`;
}

function renderModel(firm) {
  const details = firm.model_design_details || {};
  return `
    <h3>${escapeHtml(firm.firm_name || "Firm")} · Model design details</h3>
    ${renderMetricTable(Object.values(details))}`;
}

function renderNotes(firm) {
  const notes = firm.notes || [];
  const warnings = firm.extraction_warnings || [];
  return `
    <h3>${escapeHtml(firm.firm_name || "Firm")} · Notes</h3>
    ${notes.length ? notes.map(note => `<div class="note-row"><strong>${escapeHtml(note.subsection || "General")}</strong><span>${escapeHtml(note.disclosure_status || "")} · ${escapeHtml(note.confidence || "")}</span><p>${escapeHtml(note.note || "")}</p></div>`).join("") : '<p class="empty">No additional notes.</p>'}
    ${warnings.length ? `<h4>Validation warnings</h4>${warnings.map(warning => `<p class="warn">${escapeHtml(warning)}</p>`).join("")}` : ""}`;
}

function renderMetricTable(metrics = []) {
  if (!metrics.length) return '<p class="empty">No extracted metrics.</p>';
  return `
    <div class="table-scroll">
      <table>
        <tr><th>Item</th><th>Value / detail</th><th>Status</th><th>Confidence</th><th>Source</th><th>Note</th></tr>
        ${metrics.map(metric => `
          <tr>
            <td>${escapeHtml(metric?.label || "")}</td>
            <td>${escapeHtml(formatMetric(metric))}</td>
            <td>${escapeHtml(metric?.disclosure_status || "")}</td>
            <td>${escapeHtml(metric?.confidence || "")}</td>
            <td>${escapeHtml(formatSource(metric?.source))}</td>
            <td>${escapeHtml(metric?.note || "")}</td>
          </tr>`).join("")}
      </table>
    </div>`;
}

function renderCoreNotes(notes) {
  if (!notes.length) return "";
  return `<div class="core-notes">${notes.map(note => `<p>${escapeHtml(note)}</p>`).join("")}</div>`;
}

function renderCell(value) {
  if (typeof value === "string") return escapeHtml(value);
  return escapeHtml(formatMetric(value));
}

function formatMetric(metric) {
  if (!metric) return "";
  if (metric.value === null || metric.value === undefined || metric.value === "") return "Not disclosed";
  return `${metric.value}${metric.unit ? ` ${metric.unit}` : ""}`;
}

function formatSource(source) {
  if (!source) return "";
  const page = source.page ? `p. ${source.page}` : "page not cited";
  const section = source.table_or_section ? `, ${source.table_or_section}` : "";
  return `${page}${section}`;
}

function labelize(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
