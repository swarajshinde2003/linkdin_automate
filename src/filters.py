"""Filtering, deduplication, and ranking for HiringPost records."""
from __future__ import annotations

import re

from src.models import HiringPost

HIRING_SIGNALS = [
    "hiring", "we are hiring", "we're hiring", "urgent requirement",
    "urgent hiring", "opening", "job opening", "opportunity",
    "looking for", "seeking", "share resume", "send cv", "send resume",
    "apply now", "reach out", "dm me", "dm for", "recruiter",
    "talent acquisition", "connect with me", "interested candidates",
    "email me", "mail me",
]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


# ── public API ───────────────────────────────────────────────────────────────────

def apply_all(
    posts: list[HiringPost],
    require_email: bool = True,
) -> tuple[list[HiringPost], list[HiringPost]]:
    """
    Returns (confirmed_posts, review_posts).
    confirmed_posts : has hiring signal + has email (if required)
    review_posts    : has hiring signal + no email, only when require_email=False

    When require_email=True, posts without an email are silently discarded.
    """
    confirmed: list[HiringPost] = []
    review: list[HiringPost] = []

    for post in posts:
        text_l = post.raw_text.lower()

        # hiring-signal filter — skip pure noise blocks
        if not _has_hiring_signal(text_l):
            continue

        # email check
        if not post.hr_mail:
            if require_email:
                continue  # discard completely — user only wants email posts
            # email filter off: no-email posts still appear as confirmed
            confirmed.append(post)
            continue

        confirmed.append(post)

    confirmed = _deduplicate(confirmed)
    review = _deduplicate(review)

    confirmed = _rank(confirmed)
    return confirmed, review


def _has_hiring_signal(text_lower: str) -> bool:
    return any(sig in text_lower for sig in HIRING_SIGNALS)


def _deduplicate(posts: list[HiringPost]) -> list[HiringPost]:
    seen: set[str] = set()
    unique: list[HiringPost] = []
    for post in posts:
        key = _dedup_key(post)
        if key not in seen:
            seen.add(key)
            unique.append(post)
    return unique


_NOISE_PREFIX = re.compile(
    r"^(?:Search\s*\|[^\n]*\n|Feed post\s*\n|\d+\s+notifications?[^\n]*\n)+",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")


def _dedup_key(post: HiringPost) -> str:
    # Primary: if we have an email + role, that uniquely identifies the job posting
    # regardless of which account reshared it
    email = post.hr_mail.split(",")[0].strip().lower()  # use first email only for key
    role = _WHITESPACE.sub(" ", post.role.lower().strip())
    if email and role:
        return f"email:{email}|role:{role}"

    # Fallback: normalise raw text fingerprint
    raw = _NOISE_PREFIX.sub("", post.raw_text.strip())
    text_fp = _WHITESPACE.sub(" ", raw).strip()[:300]
    return f"text:{text_fp}"


def _rank(posts: list[HiringPost]) -> list[HiringPost]:
    def sort_key(p: HiringPost):
        ts = p.posted_at.timestamp() if p.posted_at else 0
        has_email = 1 if p.hr_mail else 0
        kw_count = len(p.matched_keywords)
        conf = p.confidence
        return (-ts, -has_email, -kw_count, -conf)

    return sorted(posts, key=sort_key)
