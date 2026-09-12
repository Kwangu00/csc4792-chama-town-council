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


# Reads one of our raw pipe-delimited ("|") CSV files and gives back a
# plain list of dictionaries, one dictionary per row. We use "|" instead
# of the usual comma because a lot of the text we scraped already has
# commas in it.
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


# Saves a list of dictionaries to a pipe-delimited CSV file. Before
# writing, every value in every row is passed through clean_text_value,
# so we don't have to remember to clean text everywhere else in this
# script - it just happens automatically whenever we save.
def save_pipe_csv(records: list[dict], filepath: Path):
    if not records:
        print(f"  [!] No records to save for {filepath.name}")
        return

    fieldnames = list(records[0].keys())

    cleaned_records = []
    for record in records:
        cleaned_record = {}
        for key in record:
            cleaned_record[key] = clean_text_value(record[key])
        cleaned_records.append(cleaned_record)

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

    How we do this: we search the page text for a few different "marker"
    phrases (a year, "Community Projects", or one of the sections we must
    skip), remember where in the text each one was found, and then put
    all of those markers back in the order they appear. Then we walk
    through that ordered list once, from start to finish, deciding what
    to do based on what kind of marker we're looking at.
    """
    print("Cleaning: CDF Tracker + Constituency pages, Community Projects only (privacy-safe)")

    pages = load_pipe_csv(RAW_DIR / "db-unza26-csc4792-raw_website_pages.csv")

    target_pages = []
    for page in pages:
        if "page_id=1127" in page["url"] or "page_id=2507" in page["url"]:
            target_pages.append(page)
        # TODO: add Chama North constituency page here once we have its URL

    # One simple regex pattern per kind of marker, instead of one big
    # pattern that tries to match everything at once. This makes it
    # obvious what each pattern is looking for.
    year_pattern = re.compile(r"\b20\d{2}\b")
    community_pattern = re.compile(r"Community Projects")
    grants_pattern = re.compile(r"Empowerment Grants")
    loans_pattern = re.compile(r"Empowerment Loans", re.IGNORECASE)
    boarding_bursaries_pattern = re.compile(r"Secondary Boarding Bursaries")
    skills_bursaries_pattern = re.compile(r"Skills Development Bursaries")

    all_rows = []

    for page in target_pages:
        text = page["body_text"]

        # Find every marker in this page's text and remember its
        # position and what kind of marker it is. We do this one
        # pattern at a time, so the list won't be in the right order
        # yet - we fix that with a sort right after.
        markers = []

        for m in year_pattern.finditer(text):
            markers.append((m.start(), m.end(), "year", m.group()))

        for m in community_pattern.finditer(text):
            markers.append((m.start(), m.end(), "community", m.group()))

        for m in grants_pattern.finditer(text):
            markers.append((m.start(), m.end(), "skip", m.group()))

        for m in loans_pattern.finditer(text):
            markers.append((m.start(), m.end(), "skip", m.group()))

        for m in boarding_bursaries_pattern.finditer(text):
            markers.append((m.start(), m.end(), "skip", m.group()))

        for m in skills_bursaries_pattern.finditer(text):
            markers.append((m.start(), m.end(), "skip", m.group()))

        # Put the markers back in the same order they appear in the
        # actual text (they were found one pattern at a time above, so
        # right now they are grouped by kind, not by position).
        markers.sort(key=lambda marker: marker[0])

        # Now walk through the markers once, in order, from the start
        # of the text to the end.
        current_year = ""
        for i in range(len(markers)):
            _marker_start, end, kind, matched_text = markers[i]

            if kind == "year":
                current_year = matched_text
                continue

            if kind == "skip":
                # This is an Empowerment Grants/Loans or Bursaries
                # marker. We deliberately do nothing here and never
                # read the text that follows it, because those
                # sections name real people (including school
                # children), and we must not include that in the
                # dataset.
                continue

            # If we get here, kind must be "community".
            # Safe zone: everything from the end of this marker up to
            # the start of the NEXT marker of any kind. We never look
            # past that boundary - this is what keeps personal data
            # out even when it sits right next to project data in the
            # source text.
            chunk_start = end
            if i + 1 < len(markers):
                chunk_end = markers[i + 1][0]
            else:
                chunk_end = len(text)
            chunk = text[chunk_start:chunk_end].strip()

            if not chunk:
                continue

            project_rows = split_community_projects_chunk(chunk, current_year, page["url"])
            all_rows.extend(project_rows)

    save_pipe_csv(all_rows, PROCESSED_DIR / "db-unza26-csc4792-cdf_community_projects.csv")


# Looks through a chunk of text for the pattern "SECTOR word followed by
# a TYPE word", e.g. "HEALTH Construction". This usually shows up right
# after a project's own name and description, so it's a useful marker
# for roughly where one project's text ends and the next one begins.
#
# Instead of writing one big regular expression with a long list of
# sector names and type names all joined together with "|", we keep the
# sector and type names as plain Python lists and check them one at a
# time with simple, easy-to-read patterns.
def find_sector_type_matches(chunk: str) -> list[tuple]:
    sector_words = [
        "EDUCATION", "HEALTH", "WATER AND SANITATION", "TRANSPORATION",
        "TRANSPORT", "INFRASTRUCTURE", "DEFENCE", "ENERGY", "INFORMATION",
        "COMMERCE", "TRADITIONAL/CULTURE", "TRADITIONAL", "SANITATION",
        "WASTE MANAGEMENT",
    ]
    type_words = [
        "Construction", "Procurement", "Renovation", "Drilling",
        "Rehabilitation", "Completion",
    ]

    whitespace_pattern = re.compile(r"\s+")

    matches = []

    for sector_word in sector_words:
        sector_pattern = re.compile(re.escape(sector_word), re.IGNORECASE)

        for sector_match in sector_pattern.finditer(chunk):
            # There must be at least one whitespace character right
            # after the sector word, otherwise this isn't a real
            # "SECTOR TYPE" pair.
            gap_match = whitespace_pattern.match(chunk, sector_match.end())
            if not gap_match:
                continue

            # See if one of our type words starts right after that
            # whitespace.
            matched_type_text = ""
            match_end = 0
            for type_word in type_words:
                type_pattern = re.compile(re.escape(type_word), re.IGNORECASE)
                type_match = type_pattern.match(chunk, gap_match.end())
                if type_match:
                    # Keep the actual text as it appears in the source
                    # (e.g. "procurement" or "PROCUREMENT"), not just the
                    # word from our list, so we don't lose the original
                    # casing.
                    matched_type_text = type_match.group()
                    match_end = type_match.end()
                    break

            if matched_type_text == "":
                continue

            matches.append((sector_match.start(), match_end, sector_word.upper(), matched_type_text))

    # Some sector words are contained inside another, longer sector word
    # (e.g. "SANITATION" is contained inside "WATER AND SANITATION"). Since
    # we checked each sector word separately above, a single real
    # occurrence of "WATER AND SANITATION Drilling" would otherwise be
    # counted twice: once for the full phrase, and once again for
    # "SANITATION Drilling" hiding inside it. To fix this, we sort all the
    # matches we found by position, and whenever a match starts inside a
    # match we've already kept, we throw it away as a duplicate.
    matches.sort(key=lambda item: (item[0], item[0] - item[1]))

    deduplicated_matches = []
    previous_match_end = -1
    for match in matches:
        match_start = match[0]
        match_end = match[1]
        if match_start < previous_match_end:
            continue
        deduplicated_matches.append(match)
        previous_match_end = match_end

    return deduplicated_matches


def split_community_projects_chunk(chunk: str, year: str, source_url: str) -> list[dict]:
    """
    Take one "Community Projects" chunk of text and split it into one
    row per project.

    The text we get here isn't already split into neat rows - it's all
    one long string. To break it apart, we look for two kinds of clues:

    1. A SECTOR word followed by a TYPE word (e.g. "HEALTH Construction")
       usually comes right after a project's own name/description, so it
       marks roughly where one project's own text ends.

    2. A NUMBER immediately followed by an ALL-CAPS word (e.g. "3 CLASS
       ROOM BLOCK") usually marks the start of a project's own number
       and name.

    We walk through the chunk once, from start to end, one
    SECTOR+TYPE match at a time, and build up one row per match. This is
    real, messy PDF text, so this simple approach won't split every
    project perfectly - some ward/location text can end up attached to
    the wrong project. That's an acceptable trade-off for keeping the
    code easy to follow.
    """
    # Remove the repeated table header text that sometimes appears in
    # the middle of a chunk (e.g. "No. Project Name ... Project
    # Site/Location") - it isn't real project data.
    chunk = re.sub(
        r"No\.\s*Project Name.*?Project Site/Location", "", chunk, flags=re.IGNORECASE
    )

    number_pattern = re.compile(r"(\d{1,3})\s+([A-Z][A-Z]+)")

    sector_type_matches = find_sector_type_matches(chunk)

    rows = []
    segment_start = 0

    for i in range(len(sector_type_matches)):
        match_start, match_end, sector, project_type = sector_type_matches[i]

        # The text between where the last project's SECTOR+TYPE match
        # ended (or the start of the chunk, for the first project) and
        # this SECTOR+TYPE match is roughly this project's own number
        # and name/description.
        segment_text = chunk[segment_start:match_start]

        number_matches_in_segment = list(number_pattern.finditer(segment_text))
        if number_matches_in_segment:
            # The real project number is the one closest to the sector
            # word, i.e. the LAST number+CAPS match in this segment -
            # any earlier ones are usually stray numbers left over from
            # the previous project's ward/location text.
            last_number_match = number_matches_in_segment[-1]
            project_no = last_number_match.group(1)
            name_and_description = segment_text[last_number_match.start(2):].strip()
        else:
            project_no = ""
            name_and_description = segment_text.strip()

        # The ward/location text for THIS project is whatever comes
        # after this SECTOR+TYPE match, up until the next project's own
        # number starts (or the end of the chunk, if this is the last
        # project).
        if i + 1 < len(sector_type_matches):
            next_match_start = sector_type_matches[i + 1][0]
        else:
            next_match_start = len(chunk)

        text_between_projects = chunk[match_end:next_match_start]
        number_matches_between = list(number_pattern.finditer(text_between_projects))
        if number_matches_between:
            ward_location_raw = text_between_projects[:number_matches_between[-1].start()].strip()
        else:
            ward_location_raw = text_between_projects.strip()

        rows.append({
            "source_url": source_url,
            "year": year,
            "project_no": project_no,
            "project_name_and_description": name_and_description,
            "sector": sector,
            "type": project_type,
            "ward_location_raw": ward_location_raw,
        })

        segment_start = match_end

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

    target_rows = []
    for row in rows:
        if row["source_file"] == "Chama-South-Community-Projects.pdf" and row["extraction_method"] == "table":
            target_rows.append(row)

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

    target_rows = []
    for row in rows:
        if row["category"] == "idp" and row["page"] in ("44", "45") and row["extraction_method"] == "table":
            target_rows.append(row)

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

    target_pages = set()
    for page_number in range(279, 283):
        target_pages.add(str(page_number))

    target_rows = []
    for row in rows:
        if row["category"] == "idp" and row["page"] in target_pages and row["extraction_method"] == "table":
            target_rows.append(row)

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


# Runs all four cleaning steps, one after another, in the order the
# output files depend on being produced. Each step reads its own raw
# input file(s) and writes its own processed CSV file - they don't share
# any data with each other.
def main():
    clean_cdf_pages_community_projects()
    clean_chama_south_community_projects()
    clean_idp_population_table()
    clean_idp_revenue_forecast()


if __name__ == "__main__":
    main()
