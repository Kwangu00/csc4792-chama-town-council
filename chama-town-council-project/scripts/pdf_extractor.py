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


# Downloads one PDF and saves it under data/raw/pdfs/, so we only ever have
# to download each file once. If the file is already there from a previous
# run, we just reuse it instead of downloading it again. The council's
# server can be a bit unreliable, so if a download fails we wait a few
# seconds and try again, up to `retries` extra times, before giving up.
def download_pdf(url: str, retries: int = 2) -> Path | None:
    filename = url.split("/")[-1]
    local_path = PDF_DIR / filename

    if local_path.exists():
        print(f"  [=] Already downloaded: {filename}")
        return local_path

    for attempt in range(1, retries + 2):
        try:
            response = requests.get(url, headers=HEADERS, timeout=120, verify=VERIFY_SSL)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"  [!] Attempt {attempt} failed for {filename}: {e}")
            time.sleep(5)
            continue

        with open(local_path, "wb") as f:
            f.write(response.content)

        time.sleep(REQUEST_DELAY)
        print(f"  [+] Downloaded: {filename} ({len(response.content) // 1024} KB)")
        return local_path

    print(f"  [x] Giving up on {filename} after {retries + 1} attempts")
    return None


# Goes through a PDF page by page and pulls out its data. For each page we
# first try pdfplumber's table detection, since these documents are
# genuinely tabular (project name, sector, ward, amount, etc. in columns)
# and that preserves the column structure far better than plain text would.
# Some government PDFs are scanned or don't use real table gridlines though,
# so if no table is found on a page, we fall back to grabbing its plain
# text instead, one output row per line. Every row we produce is tagged
# with the source's metadata (category, year, constituency) so nothing
# loses that context once all the files are combined later.
def extract_tables(pdf_path: Path, source_meta: dict) -> list[dict]:
    rows_out = []

    try:
        with pdfplumber.open(pdf_path) as pdf:

            # Step 1: go through every page in the PDF, one at a time.
            for page_num, page in enumerate(pdf.pages, start=1):

                tables_on_this_page = page.extract_tables()
                page_had_table_rows = False

                # Step 2: go through every table pdfplumber found on this
                # page (there can be more than one table per page).
                for table in tables_on_this_page:

                    # Step 3: go through every row in this table.
                    for row in table:
                        if not row:
                            continue

                        # A row where every cell is blank isn't real data
                        # (usually just pdfplumber picking up an empty
                        # gridline), so we check each cell one at a time
                        # and skip the row if none of them have any text.
                        row_is_empty = True
                        for cell in row:
                            if cell is not None and str(cell).strip() != "":
                                row_is_empty = False
                                break

                        if row_is_empty:
                            continue

                        page_had_table_rows = True

                        cell_texts = []
                        for cell in row:
                            if cell is None:
                                cell_texts.append("")
                            else:
                                cell_texts.append(str(cell).strip())

                        rows_out.append({
                            "source_file": pdf_path.name,
                            "category": source_meta["category"],
                            "year": source_meta["year"],
                            "constituency": source_meta["constituency"],
                            "page": page_num,
                            "extraction_method": "table",
                            "row_data": " | ".join(cell_texts),
                        })

                # Fallback: no table detected on this page — grab plain text
                # instead so we still capture the content, one line per row.
                if not page_had_table_rows:
                    text = page.extract_text() or ""
                    lines = text.split("\n")
                    for line in lines:
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


# Writes all the extracted rows out to one pipe-delimited CSV file, so
# every PDF's data ends up combined together in a single place. We use "|"
# instead of a comma because some of the extracted text already contains
# commas.
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


# Runs the whole pipeline in order: download every PDF we know about,
# extract its data, then save everything to one combined CSV file at the
# end.
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