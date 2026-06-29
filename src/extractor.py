"""Extraction logic -- three-tier LLM strategy:

  Tier 1 (Remote gpt-4o-compatible)  -- REMOTE_LLM_BASE_URL set in .env
          Supports text extraction + image OCR via vision API.
  Tier 2 (Local Ollama)              -- text extraction only.
  Tier 3 (Rules only)                -- regex email/URL, always runs as baseline.

The app is fully functional with rules-only; each LLM tier improves
role / company / location / experience accuracy.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional

import requests
from dotenv import load_dotenv

from src.models import HiringPost

load_dotenv()

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_LINKEDIN_URL_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/[^\s\"'>]+")

# New unified LLM settings (take priority when set)
_LLM_BASE_URL   = os.getenv("LLM_BASE_URL",   "").rstrip("/")
_LLM_MODEL      = os.getenv("LLM_MODEL",       "")
_LLM_API_KEY    = os.getenv("OLLAMA_API_KEY",  "NO_API_KEY")
_LLM_TEMP       = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# Legacy settings (used only when LLM_BASE_URL is not set)
OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL",        "llama3")
REMOTE_BASE_URL  = os.getenv("REMOTE_LLM_BASE_URL", "").rstrip("/")
REMOTE_API_KEY   = os.getenv("REMOTE_LLM_API_KEY",  "NO_API_KEY")
REMOTE_MODEL     = os.getenv("REMOTE_LLM_MODEL",    "gpt-4o")

# Resolved active endpoint: new LLM_BASE_URL wins over legacy REMOTE_LLM_BASE_URL
_ACTIVE_BASE_URL = _LLM_BASE_URL or REMOTE_BASE_URL
_ACTIVE_MODEL    = _LLM_MODEL    or REMOTE_MODEL
_ACTIVE_API_KEY  = _LLM_API_KEY  if _LLM_BASE_URL else REMOTE_API_KEY

# Vision/OCR is only available on models that explicitly support it.
# We enable it only when REMOTE_LLM_MODEL=gpt-4o is set (legacy remote path).
_OCR_ENABLED = bool(REMOTE_BASE_URL) and "gpt-4o" in REMOTE_MODEL.lower()

_EXTRACT_PROMPT = """\
You are an information extraction assistant. Extract job details from the LinkedIn post below.
Return ONLY valid JSON with these keys (use empty string if not found):
  role, company, location, experience, hr_mail

Rules:
- role: exact job title mentioned (e.g. "GenAI Engineer", "ML Lead")
- company: hiring company name
- location: city/state (e.g. "Pune", "Bengaluru", "Remote")
- experience: years of experience required — return as simple format like "3", "5", "7-10", etc (e.g. "3-5 years" → return "3-5", "5+ yrs" → return "5+", "Fresher" → return "Fresher", "")
- hr_mail: ALL email addresses present in the post, comma-separated (any type — recruiter, HR, personal, company), else ""

Post:
---
{text}
---

JSON:"""

_OCR_PROMPT = """\
This image is from a LinkedIn hiring post. Extract all readable text from it.
Return plain text only, no JSON, no markdown."""


def _extract_min_experience_years(experience_str: str) -> str:
    """Extract minimum experience value as integer from experience string.
    
    Examples:
        "3-5 years" → "3"
        "5+ years" → "5"
        "Fresher" → "0"
        "2-3 yrs" → "2"
        "" → ""
    """
    if not experience_str or not isinstance(experience_str, str):
        return ""
    
    exp_lower = experience_str.lower().strip()
    
    # Handle "fresher" case
    if "fresher" in exp_lower:
        return "0"
    
    # Extract the first number found in the string
    numbers = re.findall(r'\d+', exp_lower)
    if numbers:
        return numbers[0]  # Return the first (minimum) number found
    
    return ""


# ── public API ───────────────────────────────────────────────────────────────────

def extract(raw: dict, keywords: list[str]) -> HiringPost:
    """Return a HiringPost built from rules + best available LLM."""
    text = raw.get("raw_text", "")
    post_link = raw.get("post_link", "")
    source = raw.get("source", "")
    posted_at_raw = raw.get("posted_at_raw", "")
    images: list[str] = raw.get("images", [])  # base64 data URIs or http URLs

    # --- rules layer (always runs) ---
    emails = list(dict.fromkeys(e.lower() for e in _EMAIL_RE.findall(text)))  # unique, ordered
    hr_mail = ", ".join(emails) if emails else ""
    if not post_link:
        # Prefer actual post/activity URLs over profile/company URLs
        for pattern in [
            r"https?://(?:www\.)?linkedin\.com/(?:posts|feed/update)/[^\s\"'<>]+",
            r"https?://(?:www\.)?linkedin\.com/[^\s\"'<>]+",
        ]:
            m = re.search(pattern, text)
            if m:
                post_link = m.group(0).split("?")[0]
                break

    matched = [kw for kw in keywords if kw.lower() in text.lower()]
    confidence = len(matched) / max(len(keywords), 1)

    post = HiringPost(
        hr_mail=hr_mail,
        post_link=post_link,
        source=source,
        posted_at_raw=posted_at_raw,
        matched_keywords=matched,
        confidence=confidence,
        raw_text=text[:5000],
    )

    # --- OCR images (only when REMOTE_LLM_MODEL=gpt-4o is configured) ---
    if images and _OCR_ENABLED:
        ocr_texts = [_remote_ocr(img) for img in images[:3]]  # cap at 3 images
        extra_text = "\n".join(t for t in ocr_texts if t)
        if extra_text:
            text = text + "\n[OCR from images]\n" + extra_text
            post.raw_text = (post.raw_text + "\n" + extra_text)[:1000]
            if not post.hr_mail:
                ocr_emails = list(dict.fromkeys(e.lower() for e in _EMAIL_RE.findall(extra_text)))
                if ocr_emails:
                    post.hr_mail = ", ".join(ocr_emails)

    # --- LLM enhancement: Tier 1 active endpoint, Tier 2 local ollama ---
    llm_data = _remote_extract(text) if _ACTIVE_BASE_URL else None
    if llm_data is None:
        llm_data = _ollama_extract(text)

    if llm_data:
        post.role       = llm_data.get("role", "")       or post.role
        post.company    = llm_data.get("company", "")    or post.company
        post.location   = llm_data.get("location", "")   or post.location
        post.experience = llm_data.get("experience", "")
        if not post.hr_mail:
            mail = llm_data.get("hr_mail", "")
            if mail:
                # LLM may return one or several emails; validate via the model
                post.hr_mail = mail.strip()
        post.confidence = min(post.confidence + 0.3, 1.0)

    # Extract minimum experience years as integer for filtering
    post.experience = _extract_min_experience_years(post.experience)

    # parse posted_at — prefer explicit posted_at_raw, fall back to scanning raw_text
    post.posted_at = _parse_timestamp(posted_at_raw) or _scan_text_for_timestamp(text)

    return post


# ── private helpers ───────────────────────────────────────────────────────────────

def _remote_extract(text: str) -> Optional[dict]:
    """Call the active OpenAI-compatible /chat/completions endpoint."""
    try:
        prompt = _EXTRACT_PROMPT.format(text=text[:2000])
        resp = requests.post(
            f"{_ACTIVE_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {_ACTIVE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": _ACTIVE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": _LLM_TEMP,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content: str = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"```(?:json)?", "", content).strip("` \n")
        parsed = json.loads(content)
        # LLM sometimes returns a list — take the first element
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else {}
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception as e:
        # Log for debugging but don't crash
        print(f"[extractor] LLM call failed: {e}")
        return None


def _remote_ocr(image_data: str) -> str:
    """Send a base64 image or URL to the active vision model and return text."""
    if not _ACTIVE_BASE_URL:
        return ""
    try:
        if image_data.startswith("http"):
            image_part = {"type": "image_url", "image_url": {"url": image_data}}
        else:
            if not image_data.startswith("data:"):
                image_data = f"data:image/png;base64,{image_data}"
            image_part = {"type": "image_url", "image_url": {"url": image_data}}

        resp = requests.post(
            f"{_ACTIVE_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {_ACTIVE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": _ACTIVE_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _OCR_PROMPT},
                        image_part,
                    ],
                }],
                "temperature": 0.0,
            },
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


def _ollama_extract(text: str) -> Optional[dict]:
    """Call Ollama /api/generate and return parsed JSON or None on any error."""
    try:
        prompt = _EXTRACT_PROMPT.format(text=text[:2000])
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        response_text: str = resp.json().get("response", "")
        # strip any markdown code fences
        response_text = re.sub(r"```(?:json)?", "", response_text).strip("` \n")
        return json.loads(response_text)
    except Exception:
        return None


def _parse_timestamp(raw: str):
    """Best-effort parse of relative or absolute timestamps found in posts."""
    if not raw:
        return None
    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc)
    raw_l = raw.lower().strip()

    patterns = [
        (re.compile(r"(\d+)\s*h(?:ours?)?(?:\s*ago)?"), lambda m: now - timedelta(hours=int(m.group(1)))),
        (re.compile(r"(\d+)\s*m(?:in(?:utes?)?)?(?:\s*ago)?"), lambda m: now - timedelta(minutes=int(m.group(1)))),
        (re.compile(r"(\d+)\s*d(?:ays?)?(?:\s*ago)?"), lambda m: now - timedelta(days=int(m.group(1)))),
        (re.compile(r"just now|moments? ago"), lambda m: now),
    ]
    for pattern, calc in patterns:
        m = pattern.search(raw_l)
        if m:
            try:
                return calc(m)
            except Exception:
                pass

    # Try ISO / common date strings
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def _scan_text_for_timestamp(text: str):
    """Scan raw post text for common timestamp phrases and return a datetime."""
    _TS_PATTERNS = [
        re.compile(r"(\d+)\s*hour[s]?\s*ago", re.IGNORECASE),
        re.compile(r"(\d+)\s*hr[s]?\s*ago", re.IGNORECASE),
        re.compile(r"(\d+)\s*h\s*ago", re.IGNORECASE),
        re.compile(r"(\d+)\s*min(?:ute)?[s]?\s*ago", re.IGNORECASE),
        re.compile(r"(\d+)\s*day[s]?\s*ago", re.IGNORECASE),
        re.compile(r"just now", re.IGNORECASE),
        re.compile(r"moments?\s*ago", re.IGNORECASE),
        re.compile(r"posted\s+(\d+)\s*h(?:ours?)?", re.IGNORECASE),
        re.compile(r"posted\s+(\d+)\s*day[s]?", re.IGNORECASE),
    ]
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)

    for pat in _TS_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                n = int(m.group(1)) if m.lastindex and m.lastindex >= 1 else 0
                pattern_str = pat.pattern.lower()
                if "hour" in pattern_str or r"\bh\b" in pattern_str or "hr" in pattern_str:
                    return now - timedelta(hours=n)
                if "min" in pattern_str:
                    return now - timedelta(minutes=n)
                if "day" in pattern_str:
                    return now - timedelta(days=n)
                return now  # just now / moments ago
            except Exception:
                pass
    return None
