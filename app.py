from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ifrs9_benchmark.pipeline import BenchmarkPipeline


BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
UPLOADS_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"

for directory in (RUNS_DIR, UPLOADS_DIR, STATIC_DIR):
    directory.mkdir(exist_ok=True)

app = FastAPI(title="IFRS 9 Benchmarking Studio")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/reports")
async def create_report(
    files: list[UploadFile] = File(...),
    parser: str = Form("auto"),
    llm_model: str = Form("llama-3.3-70b-versatile"),
    max_pages_per_pdf: int = Form(80),
) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one PDF.")
    if len(files) > 15:
        raise HTTPException(status_code=400, detail="Maximum 15 PDFs are supported.")

    run_id = uuid.uuid4().hex[:12]
    run_dir = RUNS_DIR / run_id
    upload_dir = UPLOADS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths: list[Path] = []
    for uploaded in files:
        if not uploaded.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{uploaded.filename} is not a PDF.")
        target = upload_dir / Path(uploaded.filename).name
        with target.open("wb") as handle:
            shutil.copyfileobj(uploaded.file, handle)
        pdf_paths.append(target)

    try:
        pipeline = BenchmarkPipeline(
            output_dir=run_dir,
            parser_preference=parser,
            llm_model=llm_model,
            max_pages_per_pdf=max(8, min(max_pages_per_pdf, 200)),
        )
        result = pipeline.run(pdf_paths)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(
        {
            "run_id": run_id,
            "summary": result["summary"],
            "json_url": f"/api/reports/{run_id}/json",
            "html_url": f"/api/reports/{run_id}/html",
            "pdf_url": f"/api/reports/{run_id}/pdf",
        }
    )


@app.get("/api/reports/{run_id}/json")
def get_json(run_id: str) -> FileResponse:
    path = RUNS_DIR / run_id / "benchmark_report.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(path, media_type="application/json", filename="benchmark_report.json")


@app.get("/api/reports/{run_id}/html", response_class=HTMLResponse)
def get_html(run_id: str) -> str:
    path = RUNS_DIR / run_id / "benchmark_report.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return path.read_text(encoding="utf-8")


@app.get("/api/reports/{run_id}/pdf")
def get_pdf(run_id: str) -> FileResponse:
    path = RUNS_DIR / run_id / "benchmark_report.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(path, media_type="application/pdf", filename="ifrs9_benchmark_report.pdf")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "groq_configured": bool(os.environ.get("GROQ_API_KEY"))}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
