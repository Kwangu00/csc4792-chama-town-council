"""
scripts/data_cleaning.py

Turns the raw scraped/extracted files into clean, structured CSVs.

We start with the CDF Tracker table, because it is the best-structured
source we have. More cleaning steps for the other raw files (budget, IDP,
news articles) get added here as we go.

Run this with:
    python scripts/data_cleaning.py
"""

import csv
import re
from pathlib import Path

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_pipe_csv(filepath: Path) -> list[dict]:
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="|")
        return list(reader)


def clean_text_value(value: str) -> str:
    """
    Some cell values contain a broken line-wrap from the original PDF —
    either as a real newline character, or (as it turns out for this
    data) as the literal two-character text "\\n" that ended up embedded
    in the string itself. We replace both forms with a single space and
    collapse any resulting double spaces, so words don't stay broken
    apart in the final dataset.
    """
    if not isinstance(value, str):
        return value
    cleaned = value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    # Also catch the literal two-character sequence backslash + n / r,
    # in case it was stored as text rather than an actual newline.
    cleaned = cleaned.replace("\\n", " ").replace("\\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def save_pipe_csv(records: list[dict], filepath: Path):
    if not records:
        print(f"  [!] No records to save for {filepath.name}")
        return
    fieldnames = list(records[0].keys())
    cleaned_records = [
        {k: clean_text_value(v) for k, v in record.items()}
        for record in records
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="|")
        writer.writeheader()
        writer.writerows(cleaned_records)
    print(f"  [+] Saved {len(cleaned_records)} rows -> {filepath}")


def clean_cdf_pages_community_projects():
    """
    Both the CDF Tracker page (page_id=1127) and the Constituency pages
    (e.g. page_id=2507) can contain the same kind of multi-year CDF
    listing: Community Projects, Empowerment Grants, Empowerment Loans,
    Secondary Boarding Bursaries, Skills Development Bursaries — all in
    one block of text.

    Only "Community Projects" is safe to include in the dataset — it lists
    projects (schools, boreholes, etc.), not people. The other sections
    name real individuals, including school children receiving bursaries,
    so we do not extract them at all, from either page. We only ever read
    the text sitting between a "Community Projects" marker and whatever
    section comes next, and we skip past everything else untouched —
    regardless of which page it came from.
    """
    print("Cleaning: CDF Tracker + Constituency pages, Community Projects only (privacy-safe)")

    pages = load_pipe_csv(RAW_DIR / "db-unza26-csc4792-raw_website_pages.csv")
    target_pages = [
        p for p in pages
        if "page_id=1127" in p["url"] or "page_id=2507" in p["url"]
        # TODO: add Chama North constituency page here once we have its URL
    ]

    marker_pattern = re.compile(
        r"(?P<year>\b20\d{2}\b)"
        r"|(?P<community>Community Projects)"
        r"|(?P<empowerment_grants>Empowerment Grants)"
        r"|(?P<empowerment_loans>Empowerment [Ll]oans)"
        r"|(?P<bursaries>Secondary Boarding Bursaries|Skills Development Bursaries)"
    )

    all_rows = []

    for page in target_pages:
        text = page["body_text"]
        matches = list(marker_pattern.finditer(text))

        current_year = ""
        for i, m in enumerate(matches):
            kind = m.lastgroup
            if kind == "year":
                current_year = m.group("year")
                continue

            if kind == "community":
                # Safe zone: everything from here to the next marker of ANY
                # kind. We never look past that boundary — this is what
                # keeps personal data out even when it sits right next to
                # project data in the source text.
                chunk_start = m.end()
                chunk_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                chunk = text[chunk_start:chunk_end].strip()

                if not chunk:
                    continue

                project_rows = split_community_projects_chunk(
                    chunk, year=current_year, source_url=page["url"]
                )
                all_rows.extend(project_rows)

            # empowerment_grants / empowerment_loans / bursaries markers:
            # deliberately do nothing. We never read the text after them
            # here — the loop just moves on to the next marker.

    save_pipe_csv(all_rows, PROCESSED_DIR / "db-unza26-csc4792-cdf_community_projects.csv")


def split_community_projects_chunk(chunk: str, year: str, source_url: str) -> list[dict]:
    """
    Split one "Community Projects" chunk of text into individual project
    rows.

    Two anchors are used together:

    1. SECTOR + TYPE pair (e.g. "HEALTH construction") marks the end of a
       project's own name+description — matching the pair, not just the
       bare sector word, avoids false hits inside project names like
       "HEALTH POST IN MAIMBI" (see the SECTOR_TYPE_PATTERN docstring
       below for why).

    2. A NUMBER immediately followed by an ALL-CAPS word (e.g. "3 CLASS
       ROOM BLOCK") marks the START of the next project's own name. The
       text between one project's SECTOR+TYPE and the next project's
       number is a mix of the first project's ward/location and the
       second project's leading number+name — this second anchor is what
       lets us split that mixed text apart correctly, rather than leaving
       the two projects' data tangled together in one field.
    """
    sector_words = r"(EDUCATION|HEALTH|WATER AND SANITATION|TRANSPORATION|TRANSPORT|INFRASTRUCTURE|DEFENCE|ENERGY|INFORMATION|COMMERCE|TRADITIONAL(?:/CULTURE)?|SANITATION|WASTE MANAGEMENT)"
    type_words = r"(Construction|Procurement|Renovation|Drilling|Rehabilitation|Completion)"
    sector_type_pattern = re.compile(sector_words + r"\s+" + type_words, re.IGNORECASE)
    project_number_pattern = re.compile(r"\b(\d{1,3})\s+([A-Z][A-Z]+)")

    chunk = re.sub(
        r"No\.\s*Project Name.*?Project Site/Location", "", chunk, flags=re.IGNORECASE
    )

    matches = list(sector_type_pattern.finditer(chunk))
    rows = []

    for i, sm in enumerate(matches):
        # The raw text between the PREVIOUS sector+type match (or the very
        # start of the chunk) and THIS sector+type match. This blob mixes
        # the tail end of the previous project's ward/location with the
        # lead-in (number + name + description) of the current project.
        blob_start = matches[i - 1].end() if i > 0 else 0
        blob = chunk[blob_start:sm.start()]

        # Find where THIS project's own number+name actually starts,
        # using the LAST "number + CAPS word" match in the blob — the
        # true project number is always the one closest to the sector,
        # not any stray numbers earlier in the previous project's text.
        number_matches = list(project_number_pattern.finditer(blob))

        if number_matches:
            split = number_matches[-1]
            leftover_ward_location = blob[:split.start()].strip()
            project_no = split.group(1)
            name_and_description = blob[split.end() - len(split.group(2)):].strip()
        else:
            leftover_ward_location = ""
            project_no = ""
            name_and_description = blob.strip()

        # That leftover ward/location text actually belongs to the
        # PREVIOUS row, not this one — go back and fill it in now that we
        # know it.
        if i > 0 and rows:
            rows[-1]["ward_location_raw"] = leftover_ward_location

        sector = sm.group(1).upper()
        project_type = sm.group(2)

        rows.append({
            "source_url": source_url,
            "year": year,
            "project_no": project_no,
            "project_name_and_description": name_and_description,
            "sector": sector,
            "type": project_type,
            "ward_location_raw": "",  # filled in on the next iteration
        })

    # The text after the FINAL sector+type match is the last project's
    # ward/location — there's no further match to trigger filling it in,
    # so we do it once, after the loop.
    if matches and rows:
        rows[-1]["ward_location_raw"] = chunk[matches[-1].end():].strip()

    return rows


def clean_chama_south_community_projects():
    """
    The Chama South Community Projects PDF already extracted almost
    perfectly as a real table (project no, description, ward, amount,
    sector). This just splits it into proper columns and saves it —
    minimal cleaning needed since the source was already well-structured.
    """
    print("Cleaning: Chama South Community Projects (PDF)")

    rows = load_pipe_csv(RAW_DIR / "db-unza26-csc4792-raw_pdf_tables.csv")
    target_rows = [
        r for r in rows
        if r["source_file"] == "Chama-South-Community-Projects.pdf"
        and r["extraction_method"] == "table"
    ]

    cleaned = []
    for r in target_rows:
        cells = [c.strip() for c in r["row_data"].split("|")]
        # Skip header/title rows that don't have 4 real data cells
        if len(cells) < 4:
            continue
        # The real project rows start with "Project N" in the first cell
        if not cells[0].lower().startswith("project"):
            continue

        project_no = cells[0]
        description = cells[1] if len(cells) > 1 else ""
        ward = cells[2] if len(cells) > 2 else ""
        amount = cells[3] if len(cells) > 3 else ""
        sector = cells[4] if len(cells) > 4 else ""

        cleaned.append({
            "project_no": project_no,
            "description": description,
            "ward": ward,
            "amount_kwacha": amount,
            "sector": sector,
            "year": r["year"],
            "constituency": r["constituency"],
        })

    save_pipe_csv(cleaned, PROCESSED_DIR / "db-unza26-csc4792-chama_south_community_projects.csv")


def clean_idp_population_table():
    """
    Extracts the district/constituency/ward population table from the IDP
    (pages 44-45). Splits the preserved row_data columns back into named
    fields: area name, total/rural/urban population by sex, land area,
    and population density.
    """
    print("Cleaning: IDP population table")

    rows = load_pipe_csv(RAW_DIR / "db-unza26-csc4792-raw_pdf_tables.csv")
    target_rows = [
        r for r in rows
        if r["category"] == "idp" and r["page"] in ("44", "45")
        and r["extraction_method"] == "table"
    ]

    column_names = [
        "area_name", "total_both_sexes", "total_male", "total_female",
        "rural_both_sexes", "rural_male", "rural_female",
        "urban_both_sexes", "urban_male", "urban_female",
        "area_km2", "population_density",
    ]

    cleaned = []
    for r in target_rows:
        cells = [c.strip() for c in r["row_data"].split("|")]
        if len(cells) < len(column_names):
            continue

        area_name = cells[0]

        # Skip header rows: the PDF's header cell contains "PROVINCE" or
        # "DISTRICT/", and a second header row has a blank area name.
        if "PROVINCE" in area_name.upper() or "DISTRICT/" in area_name.upper():
            continue
        if not area_name:
            continue

        row_dict = dict(zip(column_names, cells))
        cleaned.append(row_dict)

    save_pipe_csv(cleaned, PROCESSED_DIR / "db-unza26-csc4792-idp_ward_population.csv")

def clean_idp_revenue_forecast():
    """
    Extracts the five-year revenue forecast table from the IDP's Financial
    Plan section (2025-2030 projections by revenue category).

    The source page mixes in two things we need to filter out:
      - a leftover historical (2019-2024) expenditure table that isn't part
        of the forecast at all — we exclude it by its known row labels
      - repeated column-header rows ("Revenue Description | 2025 | 2026 |
        ...") that appear once per revenue sub-category on the page — we
        exclude these by checking for the literal header text/values
    """
    print("Cleaning: IDP revenue forecast table")

    rows = load_pipe_csv(RAW_DIR / "db-unza26-csc4792-raw_pdf_tables.csv")
    target_pages = {str(p) for p in range(279, 283)}
    target_rows = [
        r for r in rows
        if r["category"] == "idp" and r["page"] in target_pages
        and r["extraction_method"] == "table"
    ]

    # Rows belonging to the unrelated 2019-2024 historical table that
    # happens to sit on the same page — not part of the forecast.
    historical_table_labels = {
        "personnel emoluments", "use of goods and services", "social benefits",
        "non-financial assets acquisition", "other payments", "total",
        "revenue sources",
    }

    cleaned = []
    for r in target_rows:
        cells = [c.strip() for c in r["row_data"].split("|")]
        if len(cells) < 2:
            continue

        revenue_item = cells[0]
        year_values = cells[1:]

        # Skip header rows: labelled "Revenue Description"/"S/N", or rows
        # whose "values" are just the literal year numbers repeated
        if revenue_item.lower() in ("revenue description", "s/n"):
            continue
        if year_values and year_values[0].strip() == "2025":
            continue

        # Skip the leftover historical (2019-2024) table rows
        if revenue_item.lower() in historical_table_labels:
            continue

        if not any(ch.isdigit() for ch in " ".join(year_values)):
            continue

        cleaned.append({
            "revenue_item": revenue_item,
            "year_2025": year_values[0] if len(year_values) > 0 else "",
            "year_2026": year_values[1] if len(year_values) > 1 else "",
            "year_2027": year_values[2] if len(year_values) > 2 else "",
            "year_2028": year_values[3] if len(year_values) > 3 else "",
            "year_2029": year_values[4] if len(year_values) > 4 else "",
            "year_2030": year_values[5] if len(year_values) > 5 else "",
        })

    save_pipe_csv(cleaned, PROCESSED_DIR / "db-unza26-csc4792-idp_revenue_forecast.csv")


def main():
    clean_cdf_pages_community_projects()
    clean_chama_south_community_projects()
    clean_idp_population_table()
    clean_idp_revenue_forecast()


if __name__ == "__main__":
    main()