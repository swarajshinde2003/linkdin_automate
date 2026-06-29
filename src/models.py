"""Pydantic models for LinkedIn hiring post records."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class HiringPost(BaseModel):
    role: str = ""
    company: str = ""
    location: str = ""
    experience: str = ""          # e.g. "3", "5", "0" (fresher) — minimum years as string/integer
    hr_mail: str = ""
    post_link: str = ""
    posted_at: Optional[datetime] = None
    posted_at_raw: str = ""          # original timestamp string from the post
    matched_keywords: list[str] = []
    source: str = ""                 # "paste" | "html" | "url"
    confidence: float = 0.0          # 0.0 – 1.0
    raw_text: str = ""
    needs_review: bool = False       # True when posted_at is unknown

    @field_validator("hr_mail")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Accept a single email or comma-separated list of emails."""
        if not v:
            return ""
        emails = [e.strip() for e in v.split(",") if e.strip()]
        valid = [e for e in emails if _EMAIL_RE.fullmatch(e)]
        return ", ".join(e.lower() for e in valid)

    @field_validator("location")
    @classmethod
    def normalise_location(cls, v: str) -> str:
        return v.strip().title()

    @field_validator("role", "company", "experience")
    @classmethod
    def strip_field(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def flag_review(self) -> "HiringPost":
        if self.posted_at is None:
            self.needs_review = True
        return self

    def to_row(self) -> dict:
        """Flat dict suitable for a pandas DataFrame row."""
        return {
            "role": self.role,
            "company": self.company,
            "location": self.location,
            "experience": self.experience,
            "hr_mail": self.hr_mail,
            "post_link": self.post_link,
            "posted_at": self.posted_at.isoformat() if self.posted_at else self.posted_at_raw or "unknown",
            "confidence": round(self.confidence, 2),
            "matched_keywords": ", ".join(self.matched_keywords),
            "source": self.source,
            "needs_review": self.needs_review,
        }

    def to_review_row(self) -> dict:
        row = self.to_row()
        row["raw_text"] = self.raw_text[:500]
        return row
