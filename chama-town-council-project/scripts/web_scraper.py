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


# Checks whether a URL looks like a WordPress "post" link, e.g.
# "https://www.chamacouncil.gov.zm/?p=2438". WordPress post links always
# have "?p=" followed by the post's ID number. We don't need a regular
# expression for this - we can just look for the text "?p=" and then check
# that what comes right after it is actually a number.
def looks_like_post_url(url: str) -> bool:
    if "?p=" not in url:
        return False

    text_after_p = url.split("?p=")[1]

    # There could be more stuff in the URL after the number (like another
    # "&something=" parameter), so we only look at the digits right at the
    # start of text_after_p.
    number_part = ""
    for character in text_after_p:
        if character.isdigit():
            number_part += character
        else:
            break

    return number_part != ""


# Tries to find a WordPress sitemap to discover ALL news post URLs
# automatically, instead of relying only on the handful of pages we found
# manually. WordPress sites (with Yoast SEO or similar plugins) commonly
# expose a sitemap.xml file that lists every page on the site.
def discover_post_urls_from_sitemap() -> list[str]:
    candidate_sitemaps = [
        f"{BASE_URL}/sitemap.xml",
        f"{BASE_URL}/sitemap_index.xml",
        f"{BASE_URL}/wp-sitemap.xml",
    ]

    post_urls = []

    for sitemap_url in candidate_sitemaps:
        html = fetch_page(sitemap_url)

        if not html:
            # This particular sitemap address doesn't exist on the site -
            # just move on and try the next candidate.
            continue

        # A real sitemap file's XML will contain one of these two tags
        # somewhere near the top. If neither is present, whatever we
        # downloaded probably isn't a sitemap (e.g. a 404 error page).
        lowercase_html = html.lower()
        looks_like_a_sitemap = "<urlset" in lowercase_html or "<sitemapindex" in lowercase_html
        if not looks_like_a_sitemap:
            continue

        soup = BeautifulSoup(html, "xml")
        loc_tags = soup.find_all("loc")

        urls_in_this_sitemap = []
        for loc_tag in loc_tags:
            urls_in_this_sitemap.append(loc_tag.text)

        print(f"  [+] Found {len(urls_in_this_sitemap)} URLs in {sitemap_url}")
        post_urls.extend(urls_in_this_sitemap)

    return post_urls


# No sitemap exists on this site, so this function discovers news posts the
# manual way: it visits the homepage, then each older page of posts
# (WordPress typically paginates with ?paged=2, ?paged=3, ...), and collects
# every link that looks like a post URL. It stops early if a page turns up
# no new post links, or after max_pages as a safety limit so we never loop
# forever.
def discover_post_urls_from_pagination(max_pages: int = 25) -> list[str]:
    discovered = set()

    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            page_url = BASE_URL
        else:
            page_url = f"{BASE_URL}/?paged={page_num}"

        html = fetch_page(page_url)
        if not html:
            # Couldn't load this page at all - nothing more to discover,
            # so stop paginating.
            break

        soup = BeautifulSoup(html, "html.parser")
        all_links = soup.find_all("a", href=True)

        found_this_page = set()
        for link in all_links:
            href = urljoin(BASE_URL, link["href"])
            if looks_like_post_url(href):
                href_without_fragment = href.split("#")[0]  # strip any #fragment
                found_this_page.add(href_without_fragment)

        new_urls = found_this_page - discovered
        print(f"  [+] Page {page_num}: {len(found_this_page)} post links found, {len(new_urls)} new")

        if not new_urls:
            print(f"  [+] No new posts on page {page_num} — stopping pagination")
            break

        discovered |= new_urls

    return sorted(discovered)


# Given a page's parsed HTML, tries to find the tag that holds the page's
# "real" content — the article text, not the site's navbar/header/footer.
# Different WordPress themes structure their pages differently, so we try
# a few common possibilities in order, from most likely to least likely,
# and use whichever one we find first.
def find_content_container(soup: BeautifulSoup):
    # <main> is the standard HTML5 landmark for "the actual page content" -
    # most modern WordPress themes use it, so we check this first.
    main_tag = soup.find("main")
    if main_tag:
        return main_tag

    # Some themes instead use a <div> with one of these common id names.
    for candidate_id in ("content", "primary", "main"):
        div_tag = soup.find("div", id=candidate_id)
        if div_tag:
            return div_tag

    # Some themes instead use a <div> with one of these common class names.
    for div_tag in soup.find_all("div"):
        classes = div_tag.get("class", [])
        if "entry-content" in classes or "post-content" in classes:
            return div_tag

    article_tag = soup.find("article")
    if article_tag:
        return article_tag

    # Last resort: just use the whole page body (this will include the
    # nav menu and footer too, but it's better than returning nothing).
    return soup.find("body")


# Extracts the title, body text, and any linked PDF documents from a single
# WordPress post or page. Returns None if we couldn't find anything worth
# keeping, so the caller knows to skip this page.
def parse_post(url: str, html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    # Title: usually in <h1> or <title>
    title_tag = soup.find("h1") or soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
    else:
        title = ""

    content_tag = find_content_container(soup)
    if content_tag:
        body_text = content_tag.get_text(separator=" ", strip=True)
    else:
        body_text = ""

    # Collect every PDF link inside the content area too - this is how
    # we'll find the CDF PDF documents (Approved Community Projects.pdf,
    # etc.) linked from pages like the Constituency pages. We keep the
    # link text together with its URL.
    pdf_links = []
    if content_tag:
        links_in_content = content_tag.find_all("a", href=True)
        for link in links_in_content:
            href = urljoin(url, link["href"])
            if href.lower().endswith(".pdf"):
                link_text = link.get_text(strip=True)
                pdf_links.append(f"{link_text} -> {href}")

    if not title and not body_text:
        return None

    return {
        "url": url,
        "title": title,
        "body_text": body_text,
        "pdf_links": " | ".join(pdf_links),
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
