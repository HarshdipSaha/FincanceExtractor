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

### Prerequisites

- **Python 3.9 or higher** - [Download Python](https://www.python.org/downloads/)
- Verify installation: `python --version` (Windows) or `python3 --version` (Mac)

---

### For Windows

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/HarshdipSaha/FincanceExtractor.git
   cd FincanceExtractor
   ```

2. **Install dependencies:**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configure API Keys:**
   
   Create a `.env` file in the project root with your Groq API key:
   ```powershell
   echo GROQ_API_KEY=your_api_key_here > .env
   ```
   
   Or manually create a `.env` file with:
   ```
   GROQ_API_KEY=your_actual_groq_api_key
   ```

4. **Run the application:**
   ```powershell
   python app.py
   ```
   The application will be available at `http://127.0.0.1:8000`

---

### For macOS

1. **Clone the repository:**
   ```bash
   git clone https://github.com/HarshdipSaha/FincanceExtractor.git
   cd FincanceExtractor
   ```

2. **Install dependencies:**
   ```bash
   pip3 install --upgrade pip
   pip3 install -r requirements.txt
   ```

3. **Configure API Keys:**
   
   Create a `.env` file in the project root with your Groq API key:
   ```bash
   echo "GROQ_API_KEY=your_api_key_here" > .env
   ```
   
   Or manually create a `.env` file with:
   ```
   GROQ_API_KEY=your_actual_groq_api_key
   ```

4. **Run the application:**
   ```bash
   python3 app.py
   ```
   The application will be available at `http://127.0.0.1:8000`

---

### Getting Your Groq API Key

1. Visit [https://console.groq.com/](https://console.groq.com/)
2. Sign up and get your free API key
3. Copy the key and add it to your `.env` file as shown above

## Usage

1. Upload one or more bank annual reports (PDF).
2. Select the preferred parser and LLM model.
3. Wait for the extraction pipeline to complete.
4. Download the generated benchmarking report in your preferred format.
