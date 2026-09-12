# Chama Town Council Dataset — CSC 4792 Mini Project (Project Team #29)

A dataset on Chama Town Council, Eastern Province, Zambia. Built by scraping the council website and pulling data from its published budgets, planning documents, and CDF records.

Made for CSC 4792: Data Mining and Warehousing, University of Zambia, September 2026.

## Project Overview

This project looks at Chama Town Council's finances and CDF-funded community projects. It follows the Local Government Act No. 2 of 2019 and its 2023 and 2026 amendments.

The dataset covers:

- CDF-funded projects (schools, health posts, water points, roads) by sector, ward, and year
- District and constituency population figures from the 2022 census
- The council's revenue forecast for 2025 to 2030

**NOTE:** some source documents also had personal details in them. The biggest one was a list of individual school children who got CDF bursaries. We left this out of the dataset on purpose, even though the council posted it publicly, because of the Zambian Data Protection Act (2021). Only project-level and total figures are included. See the Data Description Paper for more on this.

## Data Sources

- Chama Town Council website: https://www.chamacouncil.gov.zm (CDF Tracker, Constituency pages, District profile, news posts)
- Chama Town Council 2023 Budget (PDF)
- Chama Town Council 2024 Output-Based Budget (PDF)
- Chama District Integrated Development Plan (IDP), Feb 2025 (PDF)
- Chama South Constituency Approved Community Projects, 2024 (PDF)

## Folder Structure

chama-town-council-project/
├── data/
│ ├── raw/ # Unprocessed scraped and extracted data
│ │ └── pdfs/ # Downloaded source PDFs
│ └── processed/ # Final cleaned CSVs and codebook
├── notebooks/
│ └── scraping_and_cleaning.ipynb # Full pipeline, explained step by step
├── scripts/
│ ├── web_scraper.py # Scrapes the council website
│ ├── pdf_extractor.py # Downloads and extracts tables from PDFs
│ ├── data_cleaning.py # Cleans raw data into structured CSVs
│ └── build_codebook.py # Builds the data dictionary
├── .gitignore
└── README.md


## Final Dataset Files (data/processed/)

| File | Rows | What it is |
|---|---|---|
| `db-unza26-csc4792-cdf_community_projects.csv` | 92 | CDF projects scraped from the council's CDF Tracker and Constituency pages |
| `db-unza26-csc4792-chama_south_community_projects.csv` | 16 | Officially approved 2024 CDF projects for Chama South Constituency, from a PDF |
| `db-unza26-csc4792-idp_ward_population.csv` | 27 | 2022 census population by district, constituency, and ward |
| `db-unza26-csc4792-idp_revenue_forecast.csv` | 50 | The council's revenue forecast for 2025 to 2030, by line item |
| `db-unza26-csc4792-codebook.csv` | 22 | Explains every column in the files above |

All files use a pipe (`|`) as the separator, as required by the assignment.

## How to Run

1. Clone this repository
2. Make a virtual environment and activate it:
python -m venv .venv
.venv\Scripts\Activate.ps1

3. Install what you need:
pip install requests beautifulsoup4 lxml pdfplumber pandas ipykernel pip-system-certs

4. Open `notebooks/scraping_and_cleaning.ipynb` and run all the cells. Or run the scripts one at a time, in this order:
python scripts/web_scraper.py
python scripts/pdf_extractor.py
python scripts/data_cleaning.py
python scripts/build_codebook.py


**Note:** the council website's SSL certificate is broken on their end. Because of this, both `web_scraper.py` and `pdf_extractor.py` turn off certificate checking for this one specific site. This is explained in both scripts.

## Team Members
Project Team #29

- Kwangu Mulilo
- Zita Mbambiko
- Joshua Chota
- Sarah Nuluyele
- Izukanji Nachalwe

## Acknowledgements

CSC 4792 Data Mining and Warehousing, University of Zambia, 2025/26.

Exemplar dataset used for structure: Phiri, L. (2026). A Multi-Source Dataset for CS1 Failure Prediction [Dataset]. Kaggle.
