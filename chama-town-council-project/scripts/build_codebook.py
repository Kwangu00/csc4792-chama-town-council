"""
scripts/build_codebook.py

Generates the data dictionary (codebook) describing every column in every
processed dataset file — what it means, its type, and an example value.
This follows the same pattern as the exemplar Kaggle dataset (Phiri, 2026),
which included a "-codebook.csv" file documenting all its raw and final
datasets.

Run this with:
    python scripts/build_codebook.py
"""

import csv
from pathlib import Path

PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

CODEBOOK_ENTRIES = [
    # --- db-unza26-csc4792-cdf_community_projects.csv ---
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "source_url",
        "description": "URL of the Chama Town Council website page the project record was scraped from (either the CDF Tracker page or a Constituency page).",
        "data_type": "text (URL)",
        "example_value": "https://www.chamacouncil.gov.zm/?page_id=1127",
    },
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "year",
        "description": "The CDF funding year the project relates to, as stated on the source page.",
        "data_type": "integer (year)",
        "example_value": "2023",
    },
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "project_no",
        "description": "The project's listed number on the source page. Blank where the source page did not number that section of projects.",
        "data_type": "text",
        "example_value": "3",
    },
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "project_name_and_description",
        "description": "The project's name and description, combined into one field. The source text has no consistent separator between a project's name and its description, so these were kept together rather than split inaccurately.",
        "data_type": "text",
        "example_value": "CLASS ROOM BLOCK AT CHIKONTHA PRIMARY Construction of a 1x3 crb at Chikontha Primary School",
    },
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "sector",
        "description": "The project's sector classification as listed on the source page (e.g. EDUCATION, HEALTH, WATER AND SANITATION).",
        "data_type": "categorical text",
        "example_value": "EDUCATION",
    },
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "type",
        "description": "The type of activity carried out for the project (e.g. Construction, Procurement, Drilling, Renovation).",
        "data_type": "categorical text",
        "example_value": "Construction",
    },
    {
        "file": "db-unza26-csc4792-cdf_community_projects.csv",
        "column": "ward_location_raw",
        "description": "The ward and/or site location of the project. Because the source page has no marker between one project's location and the next project's number/name, this field may also contain a fragment of the following project's leading text.",
        "data_type": "text",
        "example_value": "Chisunga Chikontha",
    },
    # --- db-unza26-csc4792-chama_south_community_projects.csv ---
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "project_no",
        "description": "Project identifier as listed in the official Chama South Constituency Approved Community Projects PDF.",
        "data_type": "text",
        "example_value": "Project 4",
    },
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "description",
        "description": "Full description of the approved CDF project.",
        "data_type": "text",
        "example_value": "AMBULANCE FOR HEALTH DEPARTMENT",
    },
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "ward",
        "description": "Ward, or wards, the project serves. Some projects serve 'All Wards' rather than a single ward.",
        "data_type": "text",
        "example_value": "LUNZI",
    },
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "amount_kwacha",
        "description": "Approved CDF funding amount for the project, in Zambian Kwacha (ZMW).",
        "data_type": "text (formatted number, comma thousands separator)",
        "example_value": "2,700,000.00",
    },
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "sector",
        "description": "Sector classification for the project as listed in the source PDF (e.g. ROADS, HEALTH, EDUCATION, TRADITION).",
        "data_type": "categorical text",
        "example_value": "HEALTH",
    },
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "year",
        "description": "The CDF funding year the project was approved under.",
        "data_type": "integer (year)",
        "example_value": "2024",
    },
    {
        "file": "db-unza26-csc4792-chama_south_community_projects.csv",
        "column": "constituency",
        "description": "The constituency the project falls under.",
        "data_type": "categorical text",
        "example_value": "south",
    },
    # --- db-unza26-csc4792-idp_ward_population.csv ---
    {
        "file": "db-unza26-csc4792-idp_ward_population.csv",
        "column": "area_name",
        "description": "Name of the district, constituency, or ward the row describes. District and constituency rows are subtotals; ward rows are the individual areas within them.",
        "data_type": "text",
        "example_value": "Kamphemba",
    },
    {
        "file": "db-unza26-csc4792-idp_ward_population.csv",
        "column": "total_both_sexes / total_male / total_female",
        "description": "Total 2022 census population for the area, overall and split by sex.",
        "data_type": "text (formatted number, comma thousands separator)",
        "example_value": "17,392",
    },
    {
        "file": "db-unza26-csc4792-idp_ward_population.csv",
        "column": "rural_both_sexes / rural_male / rural_female",
        "description": "2022 census population classified as rural for the area, overall and split by sex.",
        "data_type": "text (formatted number, comma thousands separator)",
        "example_value": "4,469",
    },
    {
        "file": "db-unza26-csc4792-idp_ward_population.csv",
        "column": "urban_both_sexes / urban_male / urban_female",
        "description": "2022 census population classified as urban for the area, overall and split by sex. Shown as '-' where the area has no urban population recorded.",
        "data_type": "text (formatted number, comma thousands separator, or '-')",
        "example_value": "12,923",
    },
    {
        "file": "db-unza26-csc4792-idp_ward_population.csv",
        "column": "area_km2",
        "description": "Land area of the district, constituency, or ward, in square kilometres.",
        "data_type": "text (formatted number)",
        "example_value": "72.1",
    },
    {
        "file": "db-unza26-csc4792-idp_ward_population.csv",
        "column": "population_density",
        "description": "Population per square kilometre for the area.",
        "data_type": "decimal number",
        "example_value": "241.22",
    },
    # --- db-unza26-csc4792-idp_revenue_forecast.csv ---
    {
        "file": "db-unza26-csc4792-idp_revenue_forecast.csv",
        "column": "revenue_item",
        "description": "Name of the council revenue line item or category subtotal, from the IDP's five-year financial plan.",
        "data_type": "text",
        "example_value": "Market fees",
    },
    {
        "file": "db-unza26-csc4792-idp_revenue_forecast.csv",
        "column": "year_2025 ... year_2030",
        "description": "Projected revenue for that line item in the given year, in Zambian Kwacha (ZMW).",
        "data_type": "decimal number",
        "example_value": "109500",
    },
]


def build_codebook():
    print("Building codebook")
    filepath = PROCESSED_DIR / "db-unza26-csc4792-codebook.csv"
    fieldnames = ["file", "column", "description", "data_type", "example_value"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="|")
        writer.writeheader()
        writer.writerows(CODEBOOK_ENTRIES)
    print(f"  [+] Saved {len(CODEBOOK_ENTRIES)} rows -> {filepath}")


if __name__ == "__main__":
    build_codebook()