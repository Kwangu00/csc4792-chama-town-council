"""
scripts/pdf_extractor.py

Purpose:
    Download and extract tabular data from Chama Town Council's PDF
    documents: CDF Approved/Proposed Community Projects, Empowerment
    Loans/Grants (by year and constituency), the Output-Based Annual
    Budgets, and the District Integrated Development Plan (IDP).

Why it's built this way:
    - PDFs are downloaded and kept in data/raw/pdfs/ as the "source of
      truth" — anyone reviewing the dataset can open the original PDF next
      to our extracted CSV and check we didn't misread anything.
    - We use pdfplumber's table-detection instead of plain text extraction,
      because these documents are genuinely tabular (project name, sector,
      ward, amount, etc. in columns) and table-aware extraction preserves
      that structure far better than regex on raw text would.
    - Every extracted row is tagged with metadata (constituency, year,
      category) parsed from the filename, so once we later merge all these
      raw files together nothing loses its context.

Run this with:
    python scripts/pdf_extractor.py

Requires:
    pip install pdfplumber requests
"""

import csv
import re
import time
from pathlib import Path

import requests
import pdfplumber

# Same SSL situation as web_scraper.py — see that file's note for why.
VERIFY_SSL = False
if not VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "CSC4792-UNZA-StudentProject/1.0 "
        "(Educational data mining coursework; contact: kmulilo00@gmail.com)"
    )
}

REQUEST_DELAY = 2

# Every PDF we've identified so far, with the metadata we already know about
# it just from where we found it. Add more entries here as we discover them.
PDF_SOURCES = [
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2024/07/Chama-Town-Council-2024-Output-Based-Budget.pdf",
        "category": "budget", "year": 2024, "constituency": "both",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2024/03/Chama-Town-Council-2023-Budget.pdf",
        "category": "budget", "year": 2023, "constituency": "both",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/02/CHAMA-DISTRICT-INTEGRATED-DEVELOPMENT-PLAN-28_02_2025.pdf",
        "category": "idp", "year": 2025, "constituency": "both",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/06/2025-Approved-Community-Projects-Chama-South-Constituency.pdf",
        "category": "cdf_community_projects_approved", "year": 2025, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/06/2025-Community-Projects-Proposed-Chama-South-Constituency.pdf",
        "category": "cdf_community_projects_proposed", "year": 2025, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/06/2025-Approved-Loans-Chama-South.pdf",
        "category": "cdf_empowerment_loans", "year": 2025, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/06/2025-Approved-Grants-Chama-South.pdf",
        "category": "cdf_empowerment_grants", "year": 2025, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2024/09/Chama-South-Community-Projects.pdf",
        "category": "cdf_community_projects_approved", "year": 2024, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2024/04/Chama-South-Constituency-Empowerment-Loans-2024.pdf",
        "category": "cdf_empowerment_loans", "year": 2024, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2024/04/Chama-South-Constituency-Empowerment-Grant-2024.pdf",
        "category": "cdf_empowerment_grants", "year": 2024, "constituency": "south",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/06/2025-Approved-Loans-Chama-North.pdf",
        "category": "cdf_empowerment_loans", "year": 2025, "constituency": "north",
    },
    {
        "url": "https://www.chamacouncil.gov.zm/wp-content/uploads/2025/06/2025-Approved-Grants-Chama-North.pdf",
        "category": "cdf_empowerment_grants", "year": 2025, "constituency": "north",
    },
]

PDF_DIR = Path("data/raw/pdfs")
PDF_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


def download_pdf(url: str, retries: int = 2) -> Path | None:
    """
    Download a PDF to data/raw/pdfs/ if not already there. Returns local path.
    The council server is slow/unreliable for larger files, so we:
      - stream the download in chunks instead of waiting for it all at once
      - use a generous timeout
      - retry a couple of times before giving up
    """
    filename = url.split("/")[-1]
    local_path = PDF_DIR / filename

    if local_path.exists():
        print(f"  [=] Already downloaded: {filename}")
        return local_path

    for attempt in range(1, retries + 2):
        try:
            with requests.get(
                url, headers=HEADERS, timeout=120, verify=VERIFY_SSL, stream=True
            ) as response:
                response.raise_for_status()
                total_bytes = 0
                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        total_bytes += len(chunk)
            time.sleep(REQUEST_DELAY)
            print(f"  [+] Downloaded: {filename} ({total_bytes // 1024} KB)")
            return local_path
        except requests.RequestException as e:
            print(f"  [!] Attempt {attempt} failed for {filename}: {e}")
            if local_path.exists():
                local_path.unlink()  # remove partial/corrupt download
            if attempt <= retries:
                time.sleep(5)
    print(f"  [x] Giving up on {filename} after {retries + 1} attempts")
    return None


def extract_tables(pdf_path: Path, source_meta: dict) -> list[dict]:
    """
    Extract data from every page of a PDF, preferring detected tables but
    falling back to plain text when no table structure is found (common
    with government PDFs that are scanned or use plain positioned text
    instead of real table gridlines). Every row/line is tagged with source
    metadata so nothing loses context once files are combined later.
    """
    rows_out = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                page_had_table_rows = False

                for table in tables:
                    for row in table:
                        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                            continue
                        page_had_table_rows = True
                        rows_out.append({
                            "source_file": pdf_path.name,
                            "category": source_meta["category"],
                            "year": source_meta["year"],
                            "constituency": source_meta["constituency"],
                            "page": page_num,
                            "extraction_method": "table",
                            "row_data": " | ".join(
                                (str(c).strip() if c is not None else "") for c in row
                            ),
                        })

                # Fallback: no table detected on this page — grab plain text
                # instead so we still capture the content, one line per row.
                if not page_had_table_rows:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        rows_out.append({
                            "source_file": pdf_path.name,
                            "category": source_meta["category"],
                            "year": source_meta["year"],
                            "constituency": source_meta["constituency"],
                            "page": page_num,
                            "extraction_method": "text_fallback",
                            "row_data": line,
                        })
    except Exception as e:
        print(f"  [!] Failed to extract from {pdf_path.name}: {e}")
    return rows_out


def save_raw_csv(records: list[dict], filename: str):
    if not records:
        print(f"  [!] No records to save for {filename}")
        return
    filepath = RAW_DIR / filename
    fieldnames = list(records[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="|")
        writer.writeheader()
        writer.writerows(records)
    print(f"  [+] Saved {len(records)} rows -> {filepath}")


def main():
    print(f"Step 1: Downloading {len(PDF_SOURCES)} PDFs...")
    downloaded = []
    for source in PDF_SOURCES:
        local_path = download_pdf(source["url"])
        if local_path:
            downloaded.append((local_path, source))

    print("Step 2: Extracting tables from each PDF...")
    all_rows = []
    for local_path, source in downloaded:
        print(f"  Processing {local_path.name}...")
        rows = extract_tables(local_path, source)
        print(f"    [+] {len(rows)} table rows extracted")
        all_rows.extend(rows)

    print("Step 3: Saving combined raw output...")
    save_raw_csv(all_rows, "db-unza26-csc4792-raw_pdf_tables.csv")

    print("Done.")


if __name__ == "__main__":
    main()