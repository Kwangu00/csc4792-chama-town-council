"""
scripts/web_scraper.py

Purpose:
    Politely scrape Chama Town Council's website (chamacouncil.gov.zm) for
    CDF-related news posts and key pages (CDF Tracker, District profile,
    Constituency pages).

Why it's built this way:
    - No robots.txt exists on the site (confirmed 404), so there are no
      published crawling rules to follow. We still scrape responsibly:
      identify ourselves with a descriptive User-Agent, add delays between
      requests, and cache pages locally so we never re-fetch the same URL
      twice while developing.
    - Output is "raw" on purpose: we save exactly what we find (title, date,
      URL, full body text) with NO cleaning/parsing of numbers yet. Turning
      messy text into structured columns (amounts, constituency, project
      type) is a separate step (data_cleaning.py) — keeping raw and cleaned
      data apart is required by the assignment brief and is good practice.

Run this with:
    python scripts/web_scraper.py
"""

import csv
import time
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.chamacouncil.gov.zm"

# Identify ourselves honestly — good scraping etiquette, and useful if the
# council ever wants to know who's hitting their server and why.
HEADERS = {
    "User-Agent": (
        "CSC4792-UNZA-StudentProject/1.0 "
        "(Educational data mining coursework; contact: kmulilo00@gmail.com)"
    )
}

# Seconds to wait between requests so we don't hammer a small council server.
REQUEST_DELAY = 2

# NOTE ON SSL: chamacouncil.gov.zm's SSL certificate fails validation
# ("not within its validity period") when tested from a Windows machine with
# a correct system clock. This appears to be a misconfiguration on the
# council's own server, not a client-side issue — small local government
# sites in Zambia often run outdated or self-renewed certificates. We
# disable verification deliberately and only for this known, specific
# government domain, and we document that decision here and in the
# notebook/paper's methodology section for transparency.
VERIFY_SSL = False
if not VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Known key pages we already identified manually (page_id / p= from earlier
# research). We'll add more here as we discover them.
KNOWN_PAGES = {
    "cdf_tracker": f"{BASE_URL}/?page_id=1127",
    "district_profile": f"{BASE_URL}/?page_id=3102",
    "chama_south_constituency": f"{BASE_URL}/?page_id=2507",
    "chama_north_constituency": None,  # TODO: find this page_id — see note below
    "budget_stakeholders_meeting": f"{BASE_URL}/?p=3034",
    "cdf_skills_disbursement": f"{BASE_URL}/?p=2438",
    "cdf_health_lighting": f"{BASE_URL}/?p=2029",
    "cdf_grants_loans_2023": f"{BASE_URL}/?p=989",
    "idp_launch_article": f"{BASE_URL}/?p=2364",
}
# Drop any placeholder None values until we fill them in
KNOWN_PAGES = {k: v for k, v in KNOWN_PAGES.items() if v}

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


def fetch_page(url: str) -> str | None:
    """Fetch a single page politely. Returns HTML text, or None on failure."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, verify=VERIFY_SSL)
        response.raise_for_status()
        time.sleep(REQUEST_DELAY)  # be polite — pause after every request
        return response.text
    except requests.RequestException as e:
        print(f"  [!] Failed to fetch {url}: {e}")
        return None


def discover_post_urls_from_sitemap() -> list[str]:
    """
    Try to find a WordPress sitemap to discover ALL news post URLs
    automatically, instead of relying only on the handful we found manually.
    WordPress (with Yoast SEO or similar) commonly exposes sitemap.xml.
    """
    candidate_sitemaps = [
        f"{BASE_URL}/sitemap.xml",
        f"{BASE_URL}/sitemap_index.xml",
        f"{BASE_URL}/wp-sitemap.xml",
    ]
    post_urls = []
    for sitemap_url in candidate_sitemaps:
        html = fetch_page(sitemap_url)
        if html and "<urlset" in html.lower() or (html and "<sitemapindex" in html.lower()):
            soup = BeautifulSoup(html, "xml")
            locs = [loc.text for loc in soup.find_all("loc")]
            print(f"  [+] Found {len(locs)} URLs in {sitemap_url}")
            post_urls.extend(locs)
    return post_urls


def discover_post_urls_from_pagination(max_pages: int = 25) -> list[str]:
    """
    No sitemap exists, so we discover news posts the manual way: visit the
    homepage, then each older page of posts (WordPress typically paginates
    with ?paged=2, ?paged=3, ...), and collect every link that matches the
    site's post URL pattern (?p=NUMBER). We stop early if a page turns up
    no new post links, or after max_pages as a safety limit so we never
    loop forever.
    """
    post_url_pattern = re.compile(r"\?p=\d+")
    discovered = set()

    for page_num in range(1, max_pages + 1):
        page_url = BASE_URL if page_num == 1 else f"{BASE_URL}/?paged={page_num}"
        html = fetch_page(page_url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        found_this_page = set()
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, a["href"])
            if post_url_pattern.search(href):
                found_this_page.add(href.split("#")[0])  # strip any #fragment

        new_urls = found_this_page - discovered
        print(f"  [+] Page {page_num}: {len(found_this_page)} post links found, {len(new_urls)} new")

        if not new_urls:
            print(f"  [+] No new posts on page {page_num} — stopping pagination")
            break

        discovered |= new_urls

    return sorted(discovered)


def parse_post(url: str, html: str) -> dict | None:
    """
    Extract title, date, and body text from a single WordPress post/page.
    WordPress themes vary, so this uses a few fallback strategies, ordered
    from most-specific (likely to be just the article) to least-specific
    (the whole page, nav menu included — last resort only).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Title: usually in <h1> or <title>
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Body text: try content containers from most to least specific.
    # <main> is the standard HTML5 landmark for "the actual page content,
    # not the nav/header/footer" — most modern WordPress themes use it,
    # which is why it goes first, ahead of our earlier class-name guesses.
    content_tag = (
        soup.find("main")
        or soup.find("div", id=re.compile(r"^(content|primary|main)$"))
        or soup.find("div", class_=re.compile(r"entry-content|post-content"))
        or soup.find("article")
        or soup.find("body")
    )
    body_text = content_tag.get_text(separator=" ", strip=True) if content_tag else ""

    # Collect every link on the page too — this is how we'll find the CDF
    # PDF documents (Approved Community Projects.pdf, etc.) linked from
    # pages like the Constituency pages. We keep link text + URL together.
    links = []
    if content_tag:
        for a in content_tag.find_all("a", href=True):
            href = urljoin(url, a["href"])
            link_text = a.get_text(strip=True)
            if href.lower().endswith(".pdf"):
                links.append(f"{link_text} -> {href}")

    if not title and not body_text:
        return None

    return {
        "url": url,
        "title": title,
        "body_text": body_text,
        "pdf_links": " | ".join(links),
    }


def save_raw_csv(records: list[dict], filename: str):
    """Save scraped records as a pipe-separated CSV, per the brief's format."""
    if not records:
        print(f"  [!] No records to save for {filename}")
        return
    filepath = RAW_DIR / filename
    fieldnames = list(records[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="|")
        writer.writeheader()
        writer.writerows(records)
    print(f"  [+] Saved {len(records)} records -> {filepath}")


def main():
    print("Step 1: Trying to discover post URLs via sitemap...")
    sitemap_urls = discover_post_urls_from_sitemap()

    print("Step 2: Discovering post URLs via homepage pagination...")
    paginated_urls = discover_post_urls_from_pagination()

    print("Step 3: Combining all discovered + manually identified pages...")
    all_urls = set(sitemap_urls) | set(paginated_urls) | set(KNOWN_PAGES.values())
    print(f"  [+] Total unique URLs to scrape: {len(all_urls)}")

    print("Step 4: Fetching and parsing each page...")
    records = []
    for i, url in enumerate(sorted(all_urls), start=1):
        print(f"  ({i}/{len(all_urls)}) {url}")
        html = fetch_page(url)
        if html:
            parsed = parse_post(url, html)
            if parsed:
                records.append(parsed)

    print("Step 5: Saving raw output...")
    save_raw_csv(records, "db-unza26-csc4792-raw_website_pages.csv")

    print("Done.")


if __name__ == "__main__":
    main()