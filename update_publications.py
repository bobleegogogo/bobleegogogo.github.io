#!/usr/bin/env python3
"""
Fetches the latest journal publications from a Google Scholar profile and
inserts any new ones at the top of the Journal Papers section in publications.md.

Usage:
    python update_publications.py [--dry-run]

Options:
    --dry-run   Print what would be added without modifying publications.md.
"""

import re
import sys
import time
import textwrap
import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

SCHOLAR_USER_ID = "yECGOCwAAAAJ"
SCHOLAR_BASE    = "https://scholar.google.com"
SCHOLAR_PROFILE = (
    f"{SCHOLAR_BASE}/citations"
    f"?user={SCHOLAR_USER_ID}&hl=en&sortby=pubdate&cstart=0&pagesize=100"
)

PUBLICATIONS_FILE = "publications.md"

# Venues containing these keywords are treated as conferences/workshops and skipped.
CONFERENCE_KEYWORDS = [
    "conference", "proceedings", "workshop", "symposium", "congress",
    "sigspatial", "iclr", "cvpr", "iccv", "eccv", "neurips", "icml",
    "agile", "isprs annals", "arxiv", "geospatial week",
]

# Venues containing these keywords are always skipped (theses, book chapters, etc.)
SKIP_VENUE_KEYWORDS = [
    "thesis", "dissertation", "meeting abstract", "fall meeting",
    "zenodo", "preprint", "biorxiv", "engrxiv",
    "university of stuttgart", "technical university",
    "institut f",      # catches Institut für ...
    "book chapter", "chapter", "edited volume",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch(url, delay=1.5):
    """GET *url* and return a BeautifulSoup object, or exit on failure."""
    time.sleep(delay)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as exc:
        sys.exit(f"Network error fetching {url}: {exc}")

    if resp.status_code != 200:
        sys.exit(f"HTTP {resp.status_code} fetching {url}")

    html = resp.text
    # Detect bot/captcha walls
    if any(kw in html for kw in ("unusual traffic", "captcha", "g-recaptcha",
                                  "Please show you")):
        sys.exit(
            "Google Scholar returned a bot-detection page.\n"
            "Wait a while and try again, or run from a different IP / VPN."
        )
    return BeautifulSoup(html, "html.parser")


def is_conference(venue):
    v = venue.lower()
    if any(kw in v for kw in SKIP_VENUE_KEYWORDS):
        return True   # treat as non-journal (skip)
    return any(kw in v for kw in CONFERENCE_KEYWORDS)


# ── Scholar parsing ───────────────────────────────────────────────────────────

def fetch_scholar_publications():
    """Return a list of publication dicts from the Scholar profile page."""
    print(f"Fetching: {SCHOLAR_PROFILE}")
    soup = fetch(SCHOLAR_PROFILE)

    rows = soup.find_all("tr", class_="gsc_a_tr")
    if not rows:
        sys.exit(
            "No publication rows found. "
            "Google Scholar may have changed its HTML structure, "
            "or the request was blocked."
        )

    pubs = []
    for row in rows:
        title_el = row.find("a", class_="gsc_a_at")
        if not title_el:
            continue

        gray = row.find_all("div", class_="gs_gray")
        authors = gray[0].get_text(strip=True) if len(gray) > 0 else ""
        venue   = gray[1].get_text(strip=True) if len(gray) > 1 else ""

        year_el = row.find("span", class_="gsc_a_hc")
        year = year_el.get_text(strip=True) if year_el else ""

        detail_path = title_el.get("href", "")

        pubs.append({
            "title":        title_el.get_text(strip=True),
            "authors":      authors,
            "venue":        venue,
            "year":         year,
            "scholar_link": SCHOLAR_BASE + detail_path if detail_path else "",
            "paper_url":    "",   # filled in later
        })

    print(f"  Found {len(pubs)} total entries on Scholar profile.")
    return pubs


def fetch_paper_url(scholar_link):
    """Visit the Scholar detail page and return the real paper URL (best effort)."""
    if not scholar_link:
        return ""
    soup = fetch(scholar_link, delay=2.0)
    # The primary link appears in <div id="gsc_oci_title_gg"><a ...>
    link_el = soup.find("a", class_="gsc_oci_title_link")
    if link_el and link_el.get("href"):
        return link_el["href"]
    # Fallback: any <a> inside the title card
    title_div = soup.find("div", id="gsc_oci_title")
    if title_div:
        a = title_div.find("a")
        if a and a.get("href"):
            return a["href"]
    return ""


# ── publications.md helpers ───────────────────────────────────────────────────

def load_publications_md():
    with open(PUBLICATIONS_FILE, "r", encoding="utf-8") as f:
        return f.read()


def get_existing_titles(content):
    """Return titles already in publications.md (raw, for fuzzy matching via _normalize)."""
    return re.findall(r"\*\*\*(.+?)\*\*\*", content)


def get_next_journal_number(content):
    nums = re.findall(r"\*\*\(J(\d+)\)\*\*", content)
    return max((int(n) for n in nums), default=0) + 1


def format_entry(pub, number):
    """Return a formatted publications.md line for a new journal entry."""
    authors = pub["authors"]
    title   = pub["title"]
    venue   = pub["venue"]
    year    = pub["year"]
    url     = pub["paper_url"]

    # Scholar gives abbreviated names like "H Li". Convert "H Li" → "Li, H."
    # and bold the target author.
    def _normalize_author(a):
        a = re.sub(r"[\*†‡§]+$", "", a).strip()  # strip footnote markers
        if not a:
            return a
        # Already in "Last, F." form → keep
        if re.match(r"[A-Z][a-z]+,\s+[A-Z]", a):
            return a
        # "H Li" or "HJ Li" → "Li, H." / "Li, H.J."
        m = re.match(r"([A-Z]+)\s+([A-Z][a-zA-Z\-']+)$", a)
        if m:
            initials = ".".join(list(m.group(1))) + "."
            return f"{m.group(2)}, {initials}"
        return a

    parts = [p.strip() for p in authors.split(",")]
    parts = [_normalize_author(p) for p in parts if p.strip()]
    authors = ", ".join(parts)

    # Bold the target author (avoid adding a stray period after the closing **)
    authors = re.sub(r"\bLi,\s*H\b\.?", "**Li, H.**", authors)
    # Remove any period that directly follows the closing **
    authors = re.sub(r"\*\*\.", "**", authors)

    # Strip trailing year from venue string (Scholar appends ", YYYY" at the end)
    venue_clean = re.sub(r",?\s*\d{4}\s*$", "", venue).strip()
    citation = f"{venue_clean}." if venue_clean else ""
    if url:
        linked = f"[***{title}.*** {citation}]({url})"
    else:
        linked = f"***{title}.*** {citation}"

    # Compose the full entry line
    # Scholar's author string often already contains the year; if not, append it.
    if year and year not in authors:
        entry = f"**(J{number})** {authors}, {year}. {linked}"
    else:
        entry = f"**(J{number})** {authors}. {linked}"

    return entry.strip()


def insert_entry(content, entry):
    """Insert *entry* right after the Journal Papers section header."""
    marker = "<h3>Journal Papers (peer reviewed)</h3>"
    idx = content.find(marker)
    if idx == -1:
        sys.exit(f'Could not find "{marker}" in {PUBLICATIONS_FILE}')

    # Move past the header line and any immediately following blank line
    after_header = content.find("\n", idx) + 1
    if after_header < len(content) and content[after_header] == "\n":
        after_header += 1

    return content[:after_header] + entry + "\n\n" + content[after_header:]


def _normalize(text):
    """Lowercase, collapse whitespace, strip punctuation for fuzzy matching."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)  # normalize Unicode variants
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9 ]", " ", text)    # drop punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _word_overlap(a, b):
    """Fraction of words in the shorter string that appear in the longer string."""
    wa = set(a.split())
    wb = set(b.split())
    shorter = wa if len(wa) <= len(wb) else wb
    longer  = wa if len(wa) >  len(wb) else wb
    if not shorter:
        return 0.0
    return len(shorter & longer) / len(shorter)


def already_present(title, existing):
    """True if a close title match exists (handles casing/punctuation/Unicode/minor wording diffs)."""
    t = _normalize(title)
    for existing_title in existing:
        e = _normalize(existing_title)
        # Exact substring match
        if t in e or e in t:
            return True
        # High word-overlap (≥ 85 % of the shorter title's words found in the longer)
        if _word_overlap(t, e) >= 0.85:
            return True
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv

    # 1. Fetch Scholar data
    pubs = fetch_scholar_publications()

    # 2. Load current publications.md
    content = load_publications_md()
    existing_titles = get_existing_titles(content)
    next_num = get_next_journal_number(content)

    # 3. Identify new journal papers (newest first on the page → reverse for insertion)
    new_journals = []
    for pub in pubs:
        if already_present(pub["title"], existing_titles):
            continue
        if is_conference(pub["venue"]):
            print(f"  [skip – conference] {pub['title']}")
            continue
        if not pub["venue"]:
            print(f"  [skip – no venue]  {pub['title']}")
            continue
        new_journals.append(pub)

    if not new_journals:
        print("\nNo new journal publications found. publications.md is up to date.")
        return

    print(f"\n{len(new_journals)} new journal paper(s) to add:")
    for p in new_journals:
        print(f"  • [{p['year']}] {p['title']}")
        print(f"    Venue: {p['venue']}")

    # 4. Fetch real URLs (oldest new paper first so numbering is chronological)
    new_journals_ordered = list(reversed(new_journals))  # oldest first
    for pub in new_journals_ordered:
        print(f"\nFetching paper URL for: {pub['title'][:70]}…")
        pub["paper_url"] = fetch_paper_url(pub["scholar_link"])
        print(f"  URL: {pub['paper_url'] or '(not found)'}")

    # 5. Build entries and update file
    entries_added = []
    for pub in new_journals_ordered:
        entry = format_entry(pub, next_num)
        entries_added.append((next_num, entry))
        if not dry_run:
            content = insert_entry(content, entry)
            existing_titles.append(pub["title"].lower().strip())
        next_num += 1

    if dry_run:
        print("\n── DRY RUN – nothing written ──")
        for num, entry in entries_added:
            print(f"\n(J{num}):\n{textwrap.fill(entry, width=100)}")
        return

    with open(PUBLICATIONS_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\nDone! Added {len(entries_added)} entry/entries to {PUBLICATIONS_FILE}:")
    for num, _ in entries_added:
        print(f"  J{num}")


if __name__ == "__main__":
    main()
