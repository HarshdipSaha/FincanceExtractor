from pathlib import Path
from ifrs9_benchmark.pipeline import BenchmarkPipeline
import os
import sys

def test_pdfs():
    print("Testing 3 PDFs...")
    pdf_dir = Path(".")
    
    # Selecting 6 PDFs
    pdfs_to_test = [
        "Barclays-Bank-UK-PLC-Annual-Report-2025.pdf", 
        "HSBC annual-report-and-accounts.pdf", 
        "natwest-annual-report.pdf",
        "SantanderUKplc2025AnnualReport.pdf",
        "nextplc-annual-report-and-accounts-jan-2024.pdf",
        "frasers-annual-report-2025-web.pdf"
    ]
    
    pdf_paths = []
    for pdf in pdfs_to_test:
        pdf_path = pdf_dir / pdf
        if pdf_path.exists():
            pdf_paths.append(pdf_path)
            print(f"Found {pdf}")
        else:
            print(f"Missing {pdf}")
    
    if not pdf_paths:
        print("No PDFs found to test.")
        sys.exit(1)
        
    out_dir = Path("test_output_full")
    out_dir.mkdir(exist_ok=True)
    
    print("Initializing pipeline...")
    # Using a fast model or just let it use default llama-3.3-70b-versatile
    pipeline = BenchmarkPipeline(
        output_dir=out_dir,
        parser_preference="auto",
        llm_model="llama-3.3-70b-versatile",
        max_pages_per_pdf=36,  # increased to 36 to capture model design
    )
    
    print("Running pipeline...")
    try:
        result = pipeline.run(pdf_paths)
        print("Pipeline finished.")
        print(f"Summary: {result['summary']}")
        
        # Check generated output files
        for key, path in result['outputs'].items():
            if path.exists():
                print(f"Generated {key} report at {path}")
            else:
                print(f"Failed to generate {key} report at {path}")
                
    except Exception as e:
        print(f"Error running pipeline: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_pdfs()
