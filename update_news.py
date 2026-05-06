#!/usr/bin/env python3
"""
Reads the top N journal entries from publications.md, fetches their
publication months from Google Scholar, prepends new news items to
_includes/news_list.md, and adds journal/article cover thumbnails to
every news item as a two-column flex layout.

Usage:
    python update_news.py [--dry-run] [--count N]

Options:
    --dry-run   Print what would be done without modifying any file.
    --count N   Number of latest papers to feature as news (default: 5).
"""

import re
import sys
import time
import unicodedata
import urllib.parse
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
NEWS_FILE         = "_includes/news_list.md"
DEFAULT_COUNT     = 5

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


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url, delay=1.5):
    time.sleep(delay)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as exc:
        print(f"  [warn] Network error fetching {url}: {exc}")
        return None
    if resp.status_code != 200:
        print(f"  [warn] HTTP {resp.status_code} for {url}")
        return None
    html = resp.text
    if any(kw in html for kw in ("unusual traffic", "captcha", "g-recaptcha")):
        sys.exit(
            "Google Scholar returned a bot-detection page.\n"
            "Wait a while and try again, or run from a different IP."
        )
    return BeautifulSoup(html, "html.parser")


# ── Text normalization ────────────────────────────────────────────────────────

def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_overlap(a, b):
    wa = set(a.split())
    wb = set(b.split())
    shorter = wa if len(wa) <= len(wb) else wb
    longer  = wb if len(wa) <= len(wb) else wa
    if not shorter:
        return 0.0
    return len(shorter & longer) / len(shorter)


def titles_match(t1, t2):
    a, b = normalize(t1), normalize(t2)
    if a in b or b in a:
        return True
    return word_overlap(a, b) >= 0.80


# ── publications.md parser ────────────────────────────────────────────────────

# Matches lines like:  **(J34)** authors, 2026. [***Title.*** Venue.](URL)
ENTRY_RE = re.compile(
    r"\*\*\(J(\d+)\)\*\*"         # (1) journal number
    r".+?"                         # authors + year (non-greedy)
    r"\[{0,1}\*\*\*(.+?)\.\*\*\*" # (2) title  (inside bold-italic)
    r"\s*(.+?)"                    # (3) venue info
    r"\]\((.+?)\)",                # (4) URL
    re.DOTALL
)

def parse_journal_entries(content):
    """Return list of dicts with keys: number, title, venue_raw, url, year."""
    entries = []
    for m in ENTRY_RE.finditer(content):
        number    = int(m.group(1))
        title     = m.group(2).strip()
        venue_raw = m.group(3).strip().rstrip(".")
        url       = m.group(4).strip()

        # Extract year from the surrounding text (look before the link)
        snippet = content[max(0, m.start()):m.start(2)]
        yr = re.findall(r"\b(20\d\d)\b", snippet)
        year = yr[-1] if yr else ""

        entries.append({
            "number":    number,
            "title":     title,
            "venue_raw": venue_raw,
            "url":       url,
            "year":      year,
        })
    return entries


def extract_journal_name(venue_raw):
    """Strip volume/page/issue info, return clean journal name."""
    v = venue_raw.strip()
    # Remove trailing ellipsis
    v = re.sub(r'\s*[.…]{2,}$', '', v).strip()
    v = re.sub(r'\s*…$', '', v).strip()
    # Remove ", pp.N-N" or ", N-N" trailing page range
    v = re.sub(r',\s*pp?\.\s*[\d][\d\-]*$', '', v).strip()
    v = re.sub(r',\s*[\d][\d\-]+$', '', v).strip()
    # Remove ", VOL(ISSUE)" trailing
    v = re.sub(r',\s*\d+\s*\(\d+\)\s*$', '', v).strip()
    # Remove trailing " VOL (ISSUE)" e.g. " 59 (39)"
    v = re.sub(r'\s+\d+\s*\(\d+\)\s*$', '', v).strip()
    # Remove trailing standalone volume number e.g. " 237" or " 122"
    v = re.sub(r'\s+\d+\s*$', '', v).strip()
    return v


def make_description(title, max_words=8):
    """Generate a short topic description from the paper title."""
    # Prefer the part before a colon (usually the main topic)
    if ":" in title:
        candidate = title.split(":")[0].strip()
        # Only use pre-colon part if it's not just 1-2 words (some titles flip this)
        if len(candidate.split()) >= 3:
            title = candidate

    words = title.split()
    # Drop leading stopwords
    SKIP = {"a", "an", "the", "towards", "on", "novel", "new"}
    while words and words[0].lower() in SKIP:
        words.pop(0)

    desc_words = words[:max_words]
    # Drop trailing prepositions/articles
    TRAIL = {"a", "an", "the", "for", "in", "of", "with", "and", "to", "from"}
    while desc_words and desc_words[-1].lower().rstrip(".,;:") in TRAIL:
        desc_words.pop()

    return " ".join(desc_words)


# ── Google Scholar helpers ────────────────────────────────────────────────────

def fetch_scholar_entries():
    """Return list of {title, detail_link, year} from the Scholar profile."""
    print(f"Fetching Scholar profile…")
    soup = fetch(SCHOLAR_PROFILE)
    if soup is None:
        return []
    rows = soup.find_all("tr", class_="gsc_a_tr")
    result = []
    for row in rows:
        title_el = row.find("a", class_="gsc_a_at")
        if not title_el:
            continue
        year_el = row.find("span", class_="gsc_a_hc")
        year = year_el.get_text(strip=True) if year_el else ""
        detail_path = title_el.get("href", "")
        result.append({
            "title":       title_el.get_text(strip=True),
            "detail_link": SCHOLAR_BASE + detail_path if detail_path else "",
            "year":        year,
        })
    print(f"  Found {len(result)} entries on Scholar profile.")
    return result


def fetch_publication_date(detail_link):
    """
    Visit a Scholar detail page and return (year, month) strings.
    Month is zero-padded ('01'–'12').  Falls back to (year, '01').
    """
    if not detail_link:
        return "", "01"
    soup = fetch(detail_link, delay=2.0)
    if soup is None:
        return "", "01"

    # Scholar detail page: field labels in .gsc_oci_field, values in .gsc_oci_value
    fields = soup.find_all("div", class_="gsc_oci_field")
    values = soup.find_all("div", class_="gsc_oci_value")
    for field, value in zip(fields, values):
        if "publication date" in field.get_text(strip=True).lower():
            date_str = value.get_text(strip=True)  # e.g. "2026/3/1" or "2026/3" or "2026"
            parts = date_str.split("/")
            year  = parts[0] if len(parts) >= 1 else ""
            month = parts[1].zfill(2) if len(parts) >= 2 else "01"
            return year, month

    return "", "01"


# ── Journal cover fetcher ─────────────────────────────────────────────────────

def _probe(url, timeout=6):
    """Return url if a HEAD request returns 200/301/302, else empty string."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True,
                          headers={"User-Agent": HEADERS["User-Agent"]})
        if r.status_code in (200, 301, 302):
            return url
    except Exception:
        pass
    return ""


def _crossref_lookup(paper_url):
    """
    Extract the DOI from a URL and query the free CrossRef REST API.
    Returns a dict with 'publisher', 'issn_list', 'journal' or None.
    """
    m = re.search(r"10\.\d{4,}/\S+", paper_url)
    if not m:
        return None
    doi = m.group(0).rstrip(".,;)")
    try:
        r = requests.get(
            f"https://api.crossref.org/works/{doi}",
            timeout=10,
            headers={"User-Agent": "update_news_bot/1.0 (educational)"},
        )
        if r.status_code == 200:
            msg = r.json()["message"]
            return {
                "publisher":  msg.get("publisher", "").lower(),
                "issn_list":  msg.get("ISSN", []),
                "journal":    (msg.get("container-title") or [""])[0],
            }
    except Exception:
        pass
    return None


def _openalex_homepage(issn_list):
    """
    Query OpenAlex (free, no auth) for a journal source record and return
    the homepage URL, or '' if not found.
    """
    for issn in (issn_list or []):
        try:
            r = requests.get(
                f"https://api.openalex.org/sources?filter=issn:{issn}",
                timeout=8,
                headers={"User-Agent": "update_news_bot/1.0"},
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    homepage = results[0].get("homepage_url", "")
                    if homepage:
                        return homepage
        except Exception:
            pass
    return ""


def _cover_from_homepage(homepage_url):
    """
    Derive a working cover image URL from a journal's homepage URL
    using publisher-specific patterns.
    """
    if not homepage_url:
        return ""

    # Taylor & Francis: tandfonline.com/journals/{code}
    m = re.search(r"tandfonline\.com/journals/(\w+)", homepage_url, re.I)
    if m:
        url = f"https://www.tandfonline.com/action/showCoverImage?journalCode={m.group(1)}"
        return _probe(url) or ""

    # IEEE Xplore: ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber={id}
    m = re.search(r"punumber=(\d+)", homepage_url)
    if m:
        url = f"https://ieeexplore.ieee.org/cover/{m.group(1)}.jpg"
        return _probe(url) or ""

    # MDPI: mdpi.com/journal/{slug}
    m = re.search(r"mdpi\.com/journal/(\w+)", homepage_url, re.I)
    if m:
        url = f"https://www.mdpi.com/img/journals/{m.group(1)}-logo.png"
        return _probe(url) or ""

    # Elsevier: journals.elsevier.com or sciencedirect.com → ISSN from OpenAlex
    # Cover CDN: secure-ecsd.elsevier.com/covers/80/Tango2/large/{ISSN-no-dash}.jpg
    # (issn_list is not available here; handled via CrossRef in fetch_journal_cover)

    return ""


def _wikipedia_thumb(journal_name, size=150):
    """
    Query the Wikipedia API for the article image of a journal.
    Returns a Wikimedia thumbnail URL, or '' if not found or rate-limited.
    """
    try:
        enc = urllib.parse.quote(journal_name)
        url = (
            f"https://en.wikipedia.org/w/api.php"
            f"?action=query&prop=pageimages&pithumbsize={size}"
            f"&format=json&pilicense=any&titles={enc}"
        )
        r = requests.get(url, timeout=8, headers={"User-Agent": "update_news_bot/1.0"})
        if r.status_code == 429:
            print("    [warn] Wikipedia rate-limited, skipping.")
            return ""
        if r.status_code == 200:
            pages = r.json().get("query", {}).get("pages", {})
            for page in pages.values():
                t = page.get("thumbnail", {}).get("source", "")
                if t:
                    return t
    except Exception:
        pass
    return ""


def _bing_image_search(query, timeout=12):
    """
    Search Bing Images for *query* and return the first accessible image URL
    (HTTP 200), or '' if no result can be fetched.
    Bing HTML-encodes image metadata as &quot;murl&quot;:&quot;URL&quot;
    """
    try:
        r = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query, "FORM": "HDRSC2"},
            headers=HEADERS,
            timeout=timeout,
        )
        if r.status_code != 200:
            return ""
        urls = re.findall(
            r'&quot;murl&quot;:&quot;(https?://[^&]+)&quot;', r.text
        )
        for img_url in urls[:5]:   # try top 5, use first that responds with 200
            verified = _probe(img_url)
            if verified:
                return verified
    except Exception:
        pass
    return ""


# Curated map: normalised journal name → verified working cover image URL.
# Only include URLs confirmed to return HTTP 200 with image content.
_COVER_DICT = {
    # Taylor & Francis – showCoverImage endpoint (confirmed HTTP 200 image/jpeg)
    "international journal of geographical information science":
        "https://www.tandfonline.com/action/showCoverImage?journalCode=tgis20",
    "international journal of digital earth":
        "https://www.tandfonline.com/action/showCoverImage?journalCode=tjde20",
    # Wikimedia Commons (confirmed HTTP 200)
    "remote sensing of environment":
        "https://upload.wikimedia.org/wikipedia/en/3/3d/Remote_Sensing_of_Environment_cover.gif",
    # Local asset (SAGE blocks all automated access)
    "environment and planning b: urban analytics and city science":
        "/assets/images/picture/epb_cover.png",
}


def fetch_journal_cover(paper_url, journal_name=""):
    """
    Multi-strategy journal/article thumbnail lookup:
      1. CrossRef API → journal name → _COVER_DICT (curated, verified URLs).
      2. CrossRef + OpenAlex → journal homepage URL → publisher-specific pattern
         (Taylor & Francis showCoverImage, IEEE Xplore cover, MDPI logo).
      3. Wikipedia API → journal cover thumbnail (works for many major journals).
      4. OG / Twitter card image scraped from the paper page
         (works for arXiv, some open-access publishers).
      5. DuckDuckGo Images search for the journal name (last resort).
    For ScienceDirect direct-link URLs without a DOI, ISSN is extracted from
    the PII code and used for OpenAlex + Wikipedia fallback.
    All candidate URLs are verified with a HEAD request before being returned.
    Returns "" when no cover can be found.
    """
    print(f"  Fetching cover: {paper_url[:75]}…")

    # ── Strategies 1-3: CrossRef + OpenAlex + Wikipedia ───────────────────────
    cr = _crossref_lookup(paper_url)

    # Fallback: extract ISSN from ScienceDirect PII if no DOI found in URL
    if cr is None:
        pii_m = re.search(r"/pii/[SB](\d{8})", paper_url, re.I)
        if pii_m:
            digits = pii_m.group(1)
            issn_from_pii = f"{digits[:4]}-{digits[4:]}"
            cr = {"publisher": "", "issn_list": [issn_from_pii], "journal": ""}

    if cr:
        journal_norm = normalize(cr.get("journal", ""))

        # Strategy 1: Curated dictionary – fuzzy match on journal name
        if journal_norm:
            for key, candidate in _COVER_DICT.items():
                if key in journal_norm or journal_norm in key:
                    verified = _probe(candidate)
                    if verified:
                        print(f"    Cover (dict '{key[:40]}'): {verified[:70]}")
                        return verified

        # Strategy 2: OpenAlex homepage → publisher-specific cover pattern
        homepage = _openalex_homepage(cr["issn_list"])
        if homepage:
            cover = _cover_from_homepage(homepage)
            if cover:
                print(f"    Cover (homepage pattern): {cover[:70]}")
                return cover

        # Strategy 2b: Elsevier CDN via ISSN (secure-ecsd pattern)
        is_elsevier = (
            "elsevier" in cr.get("publisher", "")
            or "sciencedirect.com" in paper_url
            or (homepage and "elsevier.com" in homepage)
        )
        if is_elsevier:
            for issn in cr["issn_list"]:
                issn_clean = issn.replace("-", "")
                url = f"https://secure-ecsd.elsevier.com/covers/80/Tango2/large/{issn_clean}.jpg"
                verified = _probe(url)
                if verified:
                    print(f"    Cover (Elsevier CDN ISSN {issn}): {verified[:70]}")
                    return verified

        # Strategy 3: Wikipedia journal thumbnail
        wiki_name = cr.get("journal") or journal_name
        if wiki_name:
            time.sleep(0.5)   # be polite to Wikipedia API
            thumb = _wikipedia_thumb(wiki_name)
            if thumb:
                print(f"    Cover (Wikipedia): {thumb[:70]}")
                return thumb

    # ── Strategy 4: OG image from the paper page ──────────────────────────────
    final_url = paper_url
    if "doi.org/10." in paper_url:
        try:
            time.sleep(0.5)
            r = requests.get(paper_url, headers=HEADERS, timeout=15,
                             allow_redirects=True)
            final_url = r.url
            if final_url != paper_url:
                print(f"    → {final_url[:75]}")
        except Exception:
            pass

    soup = fetch(final_url, delay=1.2)
    if soup:
        for attr, name in [
            ("property", "og:image"),
            ("name",     "og:image"),
            ("name",     "twitter:image"),
            ("property", "twitter:image"),
        ]:
            tag = soup.find("meta", {attr: name})
            if tag and tag.get("content"):
                img = tag["content"].strip()
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http"):
                    print(f"    Cover (OG image): {img[:75]}")
                    return img

    # ── Strategy 5: Bing Images search for the journal name ─────────────────
    search_name = ""
    if cr and cr.get("journal"):
        search_name = cr["journal"]
    elif journal_name:
        search_name = journal_name

    if search_name:
        query = f"{search_name} journal cover"
        print(f"    Trying Bing Images: {query[:60]}…")
        img = _bing_image_search(query)
        if img:
            print(f"    Cover (Bing): {img[:70]}")
            return img

    print("    No cover found.")
    return ""


# ── news_list.md helpers ──────────────────────────────────────────────────────

def load_news():
    with open(NEWS_FILE, "r", encoding="utf-8") as f:
        return f.read()


def save_news(content):
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def _url_identifier(url):
    """
    Extract the most stable identifier from a URL (DOI, PII, arXiv id, etc.)
    so that minor URL variants (abs/full, http/https) still match.
    """
    url = url.strip().rstrip("/")
    # DOI: 10.NNNN/...
    m = re.search(r"(10\.\d{4,}/\S+)", url)
    if m:
        return m.group(1).lower().rstrip(".,)")
    # PII code in Elsevier / Springer URLs
    m = re.search(r"/pii/([A-Z0-9]+)", url, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # arXiv
    m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # IEEE document ID
    m = re.search(r"document/(\d+)", url)
    if m:
        return m.group(1)
    # Tandfonline: extract the DOI-like path segment
    m = re.search(r"tandfonline\.com/doi/\w+/(10\.\S+)", url)
    if m:
        return m.group(1).lower()
    # Fallback: strip scheme and www., use the rest
    return re.sub(r"^https?://(www\.)?", "", url).lower()


def url_in_news(url, news_content):
    """True if the URL (or a close variant) is already referenced in news_list.md."""
    if url in news_content:
        return True
    ident = _url_identifier(url)
    if ident and ident in news_content:
        return True
    # Also search for the identifier without scheme variations
    return bool(re.search(re.escape(ident), news_content, re.IGNORECASE))


def make_news_line(year, month, description, url, journal_name):
    """Format one news item in the established style."""
    return (
        f'<strong>{year}-{month}</strong> Accepted for a <b>Journal paper </b> about '
        f'{description} in '
        f'<a href="{url}"><em> {journal_name} </em></a>'
    )


def prepend_lines(news_content, lines):
    """Insert new lines at the very top of news_list.md."""
    insertion = "\n".join(lines) + "\n\n"
    return insertion + news_content.lstrip("\n")


# Matches a plain-text news line: starts with **YYYY-MM**
_PLAIN_LINE_RE = re.compile(r'^\*\*\d{4}-\d{2}\*\*')
_HREF_RE       = re.compile(r'href="([^"]+)"')


def add_covers_to_existing(news_content, dry_run=False):
    """
    For every plain-text news line (starts with **YYYY-MM** and has no <img>),
    fetch the article/journal OG thumbnail and wrap the line in a two-column
    flex div::

        <div class="news-item">        <!-- flex row -->
          <a href="URL"><img src="COVER"></a>   <!-- left column: thumbnail -->
          <span>original news text</span>        <!-- right column: text -->
        </div>

    Lines that already contain <img are left untouched.
    """
    lines = news_content.split("\n")
    updated = []
    changed = 0

    for line in lines:
        stripped = line.strip()

        # Skip empty lines and items that already have a cover
        if not stripped or "<img" in stripped:
            updated.append(line)
            continue

        # Only reformat plain news items
        if not _PLAIN_LINE_RE.match(stripped):
            updated.append(line)
            continue

        hrefs = _HREF_RE.findall(stripped)
        paper_url = hrefs[0] if hrefs else ""

        if not paper_url:
            updated.append(line)
            continue

        # Extract journal name from <em> tag for use as DDG search fallback
        em_m = re.search(r'<em>\s*(.+?)\s*</em>', stripped, re.IGNORECASE)
        journal_name = em_m.group(1).strip() if em_m else ""

        if dry_run:
            print(f"  [dry-run] Would fetch cover for: {paper_url[:70]}")
            updated.append(line)
            continue

        cover_url = fetch_journal_cover(paper_url, journal_name=journal_name)
        if not cover_url:
            updated.append(line)
            continue

        wrapped = (
            '<div class="news-item" style="display:flex;align-items:flex-start;'
            'margin-bottom:10px;">'
            f'<a href="{paper_url}" target="_blank" style="flex:0 0 10%;min-width:0;">'
            f'<img src="{cover_url}" '
            'style="width:100%;border:1px solid #e0e0e0;border-radius:3px;'
            'display:block;object-fit:cover;" alt="cover">'
            f'</a><div style="flex:0 0 2%;"></div>'
            f'<span style="flex:0 0 85%;min-width:0;">{stripped}</span></div>'
        )
        updated.append(wrapped)
        changed += 1

    if changed:
        print(f"  Added covers to {changed} news item(s).")
    else:
        print("  All items already have covers (or no OG image was available).")

    return "\n".join(updated)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    count   = DEFAULT_COUNT
    if "--count" in sys.argv:
        idx = sys.argv.index("--count")
        try:
            count = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    # 1. Parse publications.md for all journal entries
    with open(PUBLICATIONS_FILE, "r", encoding="utf-8") as f:
        pub_content = f.read()

    entries = parse_journal_entries(pub_content)
    if not entries:
        sys.exit("No journal entries found in publications.md.")

    # Sort descending by J number → newest first
    entries.sort(key=lambda e: e["number"], reverse=True)
    top_entries = entries[:count]

    print(f"\nTop {count} journal entries to feature as news:")
    for e in top_entries:
        print(f"  J{e['number']} [{e['year']}] {e['title'][:70]}")

    # 2. Load current news_list.md
    news_content = load_news()

    # 3. Find entries not yet in news
    to_process = []
    for e in top_entries:
        if url_in_news(e["url"], news_content):
            print(f"\n  [skip – already in news] J{e['number']}: {e['title'][:60]}")
        else:
            to_process.append(e)

    # 4. Fetch Scholar data + insert new entries
    new_lines = []
    if to_process:
        scholar_entries = fetch_scholar_entries()

        for entry in to_process:
            print(f"\nProcessing J{entry['number']}: {entry['title'][:60]}…")

            scholar_match = None
            for se in scholar_entries:
                if titles_match(entry["title"], se["title"]):
                    scholar_match = se
                    break

            if scholar_match:
                print(f"  Matched Scholar entry: {scholar_match['title'][:60]}")
                year, month = fetch_publication_date(scholar_match["detail_link"])
                if not year:
                    year = entry["year"]
            else:
                print(f"  [warn] No Scholar match found; using year from publications.md")
                year, month = entry["year"], "01"

            if not year:
                year = entry["year"] or "????"

            journal = extract_journal_name(entry["venue_raw"])
            desc    = make_description(entry["title"])

            print(f"  Date : {year}-{month}")
            print(f"  Venue: {journal}")
            print(f"  Desc : {desc}")

            line = make_news_line(year, month, desc, entry["url"], journal)
            new_lines.append((entry["number"], line))

        if new_lines:
            lines_to_insert = [line for _, line in new_lines]
            if dry_run:
                print("\n── DRY RUN: new entries that would be added ──\n")
                for num, line in new_lines:
                    print(f"(J{num}):\n{line}\n")
            else:
                news_content = prepend_lines(news_content, lines_to_insert)
                print(f"\nPrepended {len(new_lines)} new entry/entries:")
                for num, _ in new_lines:
                    print(f"  J{num}")
    else:
        print("\nNo new publications to add to news.")

    # 5. Add journal covers to every plain-text news item
    print("\n── Adding journal covers to news items ──")
    covered_news = add_covers_to_existing(news_content, dry_run)

    if not dry_run:
        save_news(covered_news)
        print(f"\nSaved {NEWS_FILE}.")
        if new_lines:
            print(
                "\nNote: Auto-generated descriptions are a starting point.\n"
                "Edit _includes/news_list.md to refine the 'about ...' text."
            )


if __name__ == "__main__":
    main()
