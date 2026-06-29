"""Input collection helpers.

Three input modes:
  - paste : raw text pasted from LinkedIn (one or multiple posts)
  - html  : saved LinkedIn HTML page (search results or individual post)
  - mhtml : saved LinkedIn MHTML / "Webpage, Single File" (.mhtml)
  - urls  : newline-separated LinkedIn post URLs (fetched without auth)
"""
from __future__ import annotations

import email as _email
import re
from typing import Generator

import requests
from bs4 import BeautifulSoup

# ── helpers ──────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://[^\s\"'>]+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_POST_SEPARATOR = re.compile(
    r"\n{3,}|(?:[-─═]{5,})|(?:^\s*\d{1,3}[.)]\s)", re.MULTILINE
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


# ── public API ───────────────────────────────────────────────────────────────────

# Matches any LinkedIn post/feed URL (used in both HTML and MHTML scanning)
_LI_POST_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:posts|feed/update)/[^\s\"'<>\\]+",
    re.IGNORECASE,
)


def _scan_for_post_links(text: str) -> list[str]:
    """Extract unique LinkedIn post URLs from any raw text/HTML/MHTML string."""
    seen: set[str] = set()
    links: list[str] = []
    for m in _LI_POST_RE.finditer(text):
        url = m.group(0).split("?")[0].rstrip("/\\= \t\r\n")
        # Skip URLs that look truncated (MHTML base64 line-wrap artifacts)
        if url.endswith("=") or len(url) < 40:
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def from_mhtml(mhtml_bytes: bytes) -> Generator[dict, None, None]:
    """Extract HTML from an MHTML file (Brave/Chrome 'Webpage, Single File').

    Chrome rewrites <a href> to cid:/about:blank on save, so normal href
    extraction yields nothing. We recover post URLs by scanning the raw MHTML
    bytes — the original URLs survive in og:url, canonical tags, data
    attributes, and JSON blobs inside the MIME payload.
    """
    try:
        msg = _email.message_from_bytes(mhtml_bytes)
        html = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not html:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
        if not html:
            html = mhtml_bytes.decode("utf-8", errors="replace")
    except Exception:
        html = mhtml_bytes.decode("utf-8", errors="replace")

    # Scan the QP-decoded HTML for LinkedIn post URLs.
    # (Scanning raw MHTML bytes finds nothing because the HTML part is
    # quoted-printable encoded and all hrefs are replaced with cid: refs.)
    mhtml_links = _scan_for_post_links(html)

    yield from _from_html_with_extra_links(html, mhtml_links)


def _from_html_with_extra_links(html: str, extra_links: list[str]) -> Generator[dict, None, None]:
    """Like from_html but seeds the fallback link pool with extra_links first."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Start with caller-supplied links (e.g. MHTML raw-scan results)
    all_post_links: list[str] = list(extra_links)

    # Also pull og:url and canonical — these are the page's own URL
    for meta in soup.find_all("meta", attrs={"property": "og:url"}):
        url = _extract_post_link(meta.get("content", ""))
        if url and url not in all_post_links:
            all_post_links.append(url)
    for link_tag in soup.find_all("link", rel=lambda r: r and "canonical" in r):
        url = _extract_post_link(link_tag.get("href", ""))
        if url and url not in all_post_links:
            all_post_links.append(url)

    # <a> hrefs (works for HTML-only saves; usually cid: in MHTML)
    for a in soup.find_all("a", href=True):
        lnk = _extract_post_link(a["href"])
        if lnk and lnk not in all_post_links:
            all_post_links.append(lnk)

    containers = _find_containers(soup)
    if len(containers) <= 2:
        yield from _from_text_split(soup, all_post_links)
        return

    seen: set[str] = set()
    _noise = re.compile(
        r"^(?:Search\s*\|[^\n]*\n|Feed post\s*\n|\d+\s+notifications?[^\n]*\n)+",
        re.IGNORECASE,
    )
    link_index = 0
    for container in containers:
        text = container.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        text = _noise.sub("", text).strip()
        if len(text) < 40:
            continue
        dedup_key = text[:300]
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        link = ""
        profile_fallback = ""
        for a in container.find_all("a", href=True):
            href = a["href"]
            lnk = _extract_post_link(href)
            if lnk:
                link = lnk
                break
            # Capture profile URL as fallback (first /in/ link in the container)
            if not profile_fallback and "/in/" in href:
                pf = href if href.startswith("http") else "https://www.linkedin.com" + href
                profile_fallback = pf.split("?")[0].rstrip("/")
        if not link and link_index < len(all_post_links):
            link = all_post_links[link_index]
            link_index += 1
        if not link and profile_fallback:
            link = profile_fallback

        time_tag = container.find("time")
        posted_raw = time_tag.get_text(strip=True) if time_tag else ""

        images: list[str] = []
        for img in container.find_all("img"):
            src: str = img.get("src", "")
            if src.startswith("data:image"):
                images.append(src)
            elif src.startswith("http") and "linkedin" in src:
                images.append(src)

        yield {
            "raw_text": text[:5000],
            "post_link": link,
            "posted_at_raw": posted_raw,
            "source": "html",
            "images": images,
        }


def from_pasted_text(text: str) -> Generator[dict, None, None]:
    """Split a block of pasted LinkedIn text into individual post chunks."""
    chunks = _POST_SEPARATOR.split(text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        yield {
            "raw_text": chunk,
            "post_link": _first_url(chunk),
            "source": "paste",
        }


def _extract_post_link(href: str) -> str:
    """Normalise a raw href into a full LinkedIn post URL, or return ''."""
    if not href:
        return ""
    # Relative URL → make absolute
    if href.startswith("/"):
        href = "https://www.linkedin.com" + href
    href = href.split("?")[0].rstrip("/")
    if "linkedin.com" not in href:
        return ""
    if any(p in href for p in ("/posts/", "/feed/update/", "/activity")):
        return href
    return ""


def from_html(html: str) -> Generator[dict, None, None]:
    """Parse a saved LinkedIn HTML page and yield post-like text blocks."""
    # Also scan raw HTML string for post URLs (catches data-* attrs, JSON blobs)
    extra = _scan_for_post_links(html)
    yield from _from_html_with_extra_links(html, extra)


def _from_text_split(soup: BeautifulSoup, post_links: list | None = None) -> Generator[dict, None, None]:
    """Text-boundary post splitter for modern LinkedIn pages with hashed CSS.

    post_links: pre-collected ordered list of post URLs from <a> tags.
                Assigned to chunks in DOM order as fallback.
    """
    body_text = soup.get_text(separator="\n", strip=True)
    body_text = re.sub(r"\n{3,}", "\n\n", body_text)

    # Primary: split on LinkedIn's own section labels
    chunks = re.split(
        r"(?:^|\n)(?:Feed post|Promoted|Sponsored)\s*\n",
        body_text,
        flags=re.IGNORECASE,
    )

    # If primary split gives only 1 chunk, fall back to blank-line chunks
    if len(chunks) <= 1:
        chunks = re.split(r"\n{2,}", body_text)

    # Regex to strip page-level noise prefixes (notification bar, page title,
    # and any residual "Feed post" line left over from the split boundary)
    _noise = re.compile(
        r"^(?:Search\s*\|[^\n]*\n|Feed post\s*\n|\d+\s+notifications?[^\n]*\n)+",
        re.IGNORECASE,
    )

    available_links = list(post_links or [])
    link_index = 0

    seen: set[str] = set()
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 50:
            continue

        # Strip leading page-level noise before deduplication
        clean = _noise.sub("", chunk).strip()
        if len(clean) < 50:
            continue
        dedup_key = clean[:300]
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # 1. Full linkedin.com URL inside the text (prefer /posts/ or /feed/update/)
        link_m = re.search(r"https?://(?:www\.)?linkedin\.com/(?:posts|feed/update)/[^\s'\"<>]+", clean)
        link = link_m.group(0) if link_m else ""

        # 1b. Any other linkedin.com URL as broader fallback (e.g. /in/ profile)
        if not link:
            any_m = re.search(r"https?://(?:www\.)?linkedin\.com/[^\s'\"<>]+", clean)
            link = any_m.group(0) if any_m else ""

        # 2. URN embedded in text → reconstruct URL
        if not link:
            urn_m = re.search(r"urn:li:(?:activity|share|ugcPost):(\d+)", clean)
            if urn_m:
                link = f"https://www.linkedin.com/feed/update/urn:li:activity:{urn_m.group(1)}/"

        # 3. Use next pre-collected post link (DOM order)
        if not link and link_index < len(available_links):
            link = available_links[link_index]
            link_index += 1

        # Timestamp hint — look for patterns like "15m •", "2h •", "1d •"
        ts_m = re.search(r"(\d+[mhd])\s*[•·]", clean)
        posted_raw = ts_m.group(0) if ts_m else ""

        yield {
            "raw_text": clean[:5000],
            "post_link": link,
            "posted_at_raw": posted_raw,
            "source": "html",
            "images": [],
        }


def _find_containers(soup: BeautifulSoup) -> list:
    """Return the best list of post containers from the saved HTML.

    Strategy (most specific → broadest):
    1. Known LinkedIn CSS class/attribute selectors
    2. <article> tags
    3. Any <div> containing an email or hiring keywords
    4. Whole <body> as last resort
    """
    # Strategy 1 — known LinkedIn feed selectors
    for selector in [
        "div.feed-shared-update-v2",
        "div.occludable-update",
        "div[data-urn]",
        "div[data-id]",
        "li.scaffold-finite-scroll__content > div",
        "div.fie-impression-container",
    ]:
        found = soup.select(selector)
        if found:
            return found

    # Strategy 2 — <article> tags
    articles = soup.find_all("article")
    if articles:
        return articles

    # Strategy 3 — divs containing hiring signals or email addresses
    _HIRING_RE = re.compile(
        r"hiring|opening|opportunity|resume|cv|apply|recruiter|"
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    )
    candidate_divs = [
        d for d in soup.find_all("div")
        if len(d.get_text()) > 100 and _HIRING_RE.search(d.get_text())
    ]
    if candidate_divs:
        candidate_divs.sort(key=lambda d: len(d.get_text()))
        selected: list = []
        used_texts: set[str] = set()
        for d in candidate_divs:
            t = d.get_text()[:200]
            if t not in used_texts:
                selected.append(d)
                used_texts.add(t)
        if selected:
            return selected[:500]

    # Strategy 4 — whole body fallback
    if soup.body:
        return [soup.body]
    return []

def from_urls(url_text: str, timeout: int = 10) -> Generator[dict, None, None]:
    """Fetch publicly accessible LinkedIn post URLs (no auth).
    Gracefully skips pages that redirect to login.
    """
    for url in url_text.splitlines():
        url = url.strip()
        if not url or not url.startswith("http"):
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            # LinkedIn redirects to /login for auth-required pages
            if "linkedin.com/login" in resp.url or resp.status_code in (401, 403):
                yield {
                    "raw_text": "",
                    "post_link": url,
                    "source": "url",
                    "_fetch_blocked": True,
                }
                continue
            yield from from_html(resp.text)
        except requests.RequestException:
            yield {
                "raw_text": "",
                "post_link": url,
                "source": "url",
                "_fetch_blocked": True,
            }


def linkedin_search_url(keywords: list[str]) -> str:
    """Build a LinkedIn people/posts search URL for manual use."""
    from urllib.parse import quote_plus
    q = quote_plus(" ".join(keywords))
    return f"https://www.linkedin.com/search/results/content/?keywords={q}&sortBy=date_posted"


# ── private ──────────────────────────────────────────────────────────────────────

def _first_url(text: str) -> str:
    m = _URL_RE.search(text)
    return m.group(0) if m else ""
