# IFRS 9 Benchmarking Studio

A high-performance extraction and benchmarking tool designed to analyze IFRS 9 disclosures in bank annual reports. Using advanced LLM-powered extraction (via Groq), it automates the process of gathering and comparing Expected Credit Loss (ECL) data across multiple financial institutions.

## Features

- **Automated PDF Parsing**: Intelligent page selection and extraction using multiple parser options.
- **LLM-Powered Extraction**: Leverages Groq-hosted Llama models for precise data point retrieval.
- **Benchmarking Reports**: Generates comprehensive comparison reports in HTML, JSON, and PDF formats.
- **FastAPI Backend**: Modern, asynchronous API for handling document uploads and pipeline orchestration.
- **Interactive UI**: Clean web interface for monitoring extraction progress and viewing results.

## Project Structure

- `app.py`: FastAPI application and API endpoints.
- `ifrs9_benchmark/`: Core logic including the pipeline, LLM integration, and reporting.
- `static/`: Frontend assets (HTML, CSS, JS).
- `requirements.txt`: Python dependencies.

## Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/HarshdipSaha/FincanceExtractor.git
   cd FincanceExtractor
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API Keys:**
   Create a `.env` file or provide a `keys/` directory with your `GROQ_API_KEY`.

4. **Run the application:**
   ```bash
   python app.py
   ```
   The application will be available at `http://127.0.0.1:8000`.

## Usage

1. Upload one or more bank annual reports (PDF).
2. Select the preferred parser and LLM model.
3. Wait for the extraction pipeline to complete.
4. Download the generated benchmarking report in your preferred format.
