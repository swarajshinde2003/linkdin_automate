"""LinkedIn Hiring Post Agent — Streamlit UI

How to run:
    streamlit run app.py

Workflow:
  1. Enter keywords (e.g. genai, hiring, pune) and filters in the sidebar
  2. Provide LinkedIn content via one of three input tabs:
       a) Paste raw text copied from LinkedIn
       b) Upload a saved LinkedIn HTML file
       c) Provide LinkedIn post URLs (one per line)
  3. Click Analyse
  4. Review confirmed posts and the 'Needs Review' bucket
  5. Download the Excel sheet
"""
from __future__ import annotations

import os
import sys

import streamlit as st
from dotenv import load_dotenv

# ensure src/ is importable when running from the project root
sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from src import collectors, extractor, filters, exporter

# ── page config ───────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LinkedIn Hiring Post Agent",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 Link din")
st.caption(
    "Paste or upload LinkedIn content → extract hiring posts with HR emails → download Excel"
)

# ── sidebar — settings ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")

    # Posts without a contact email are always discarded
    require_email = True

    st.divider()
    st.info(
        "Search LinkedIn manually with your keywords (e.g. *genai hiring pune*), "
        "save the page as HTML, then upload it below.",
        icon="ℹ️",
    )

    st.divider()
    st.subheader("🤖 LLM Status")
    import requests as _req
    _llm_url = os.getenv("LLM_BASE_URL", "").rstrip("/") or os.getenv("REMOTE_LLM_BASE_URL", "").rstrip("/")
    _llm_key = os.getenv("OLLAMA_API_KEY", "") or os.getenv("REMOTE_LLM_API_KEY", "NO_API_KEY")
    _llm_model = os.getenv("LLM_MODEL", "") or os.getenv("REMOTE_LLM_MODEL", "gpt-4o")
    remote_ok = False
    if _llm_url:
        try:
            r = _req.get(f"{_llm_url}/models", timeout=3,
                         headers={"Authorization": f"Bearer {_llm_key}"})
            remote_ok = r.ok
        except Exception:
            pass
    if remote_ok:
        _ocr_note = " + image OCR" if "gpt-4o" in _llm_model.lower() else " (text only)"
        st.success(f"LLM active: {_llm_model}{_ocr_note}")
    else:
        if _llm_url:
            st.warning(f"LLM unreachable ({_llm_url}). Trying Ollama…")
        try:
            r = _req.get(f"{os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}/api/tags", timeout=3)
            if r.ok:
                st.success(f"Ollama active · model: {os.getenv('OLLAMA_MODEL', 'llama3')}")
            else:
                st.warning("Ollama reachable but returned an error. Rules-only mode.")
        except Exception:
            st.warning("No LLM reachable. Rules-only extraction active.")

# ── main — input tabs ─────────────────────────────────────────────────────────────
tab_paste, tab_html, tab_urls = st.tabs(
    ["📋 Paste Text", "📄 Upload HTML", "🔗 Post URLs"]
)

raw_items: list[dict] = []

with tab_paste:
    st.markdown(
        "Copy post text from LinkedIn (one or many posts) and paste below. "
        "Separate multiple posts with blank lines."
    )
    pasted = st.text_area("Paste LinkedIn post text here", height=300, key="paste_input")
    if st.button("Add pasted text", key="btn_paste"):
        if pasted.strip():
            items = list(collectors.from_pasted_text(pasted))
            st.session_state["paste_items"] = items
            st.success(f"Loaded {len(items)} post chunk(s) from pasted text.")
        else:
            st.warning("Nothing to add — paste some text first.")

    raw_items += st.session_state.get("paste_items", [])

with tab_html:
    st.markdown(
        "Save LinkedIn search/post pages as HTML or MHTML, then upload one or more files."
    )
    st.warning(
        "**⚠️ Do NOT open the saved file in a browser** — LinkedIn's JS will show "
        "'Something went wrong'. That is normal. Just upload it here directly.  \n\n"
        "**Before saving:** scroll to load all posts, let the Brave extension expand "
        "all *more* buttons, then press `Ctrl+S`.  \n\n"
        "**Save type options** (in order of preference):  \n"
        "① *Webpage, HTML Only* (.html) — fastest, always works  \n"
        "② *Webpage, Single File* (.mhtml) — one file, but may stall if CDN assets fail  \n"
        "③ In DevTools Console: `copy(document.documentElement.outerHTML)` → paste into a .html file",
        icon="✂️",
    )
    html_files = st.file_uploader(
        "Upload one or more LinkedIn HTML / MHTML files",
        type=["html", "htm", "mhtml"],
        accept_multiple_files=True,
        key="html_upload",
    )
    if html_files:
        all_items: list[dict] = []
        for html_file in html_files:
            fname = html_file.name.lower()
            if fname.endswith(".mhtml"):
                file_items = list(collectors.from_mhtml(html_file.read()))
            else:
                html_content = html_file.read().decode("utf-8", errors="replace")
                file_items = list(collectors.from_html(html_content))
            all_items.extend(file_items)
            st.caption(f"📄 {html_file.name} → {len(file_items)} post(s)")
        st.session_state["html_items"] = all_items
        st.success(f"Parsed **{len(all_items)}** post block(s) from {len(html_files)} file(s).")

    raw_items += st.session_state.get("html_items", [])

with tab_urls:
    st.markdown(
        "Enter LinkedIn post URLs (one per line). "
        "Public posts will be fetched automatically; auth-required posts will be flagged."
    )
    url_text = st.text_area("LinkedIn post URLs", height=150, key="url_input")
    if st.button("Fetch URLs", key="btn_urls"):
        if url_text.strip():
            with st.spinner("Fetching posts…"):
                items = list(collectors.from_urls(url_text))
            blocked = sum(1 for i in items if i.get("_fetch_blocked"))
            st.session_state["url_items"] = items
            msg = f"Fetched {len(items)} item(s)"
            if blocked:
                msg += f" ({blocked} required login — paste their text instead)"
            st.info(msg)
        else:
            st.warning("Enter at least one URL.")

    raw_items += st.session_state.get("url_items", [])

# ── analyse button ────────────────────────────────────────────────────────────────
st.divider()
col_btn, col_count = st.columns([2, 5])
with col_btn:
    analyse = st.button("🚀 Analyse Posts", type="primary", disabled=not raw_items)
with col_count:
    st.caption(f"{len(raw_items)} raw input block(s) ready.")

if analyse and raw_items:
    progress = st.progress(0, text="Extracting…")
    posts = []
    for i, raw in enumerate(raw_items):
        progress.progress((i + 1) / len(raw_items), text=f"Extracting {i+1}/{len(raw_items)}…")
        if raw.get("_fetch_blocked"):
            continue
        try:
            p = extractor.extract(raw, [])
            posts.append(p)
        except Exception as e:
            st.warning(f"Skipped one item due to extraction error: {e}")

    progress.empty()

    confirmed, review = filters.apply_all(
        posts,
        require_email=require_email,
    )

    st.session_state["confirmed"] = confirmed
    st.session_state["review"] = review

# ── results ───────────────────────────────────────────────────────────────────────
confirmed = st.session_state.get("confirmed", [])
review = st.session_state.get("review", [])

if confirmed or review:
    st.subheader(f"✅ Confirmed Hiring Posts ({len(confirmed)})")
    if confirmed:
        import pandas as pd

        df = pd.DataFrame([p.to_row() for p in confirmed])
        df = df.rename(columns={"hr_mail": "contact_email"})
        st.dataframe(
            df[["role", "company", "location", "experience", "contact_email", "post_link", "posted_at", "confidence"]],
            use_container_width=True,
        )
    else:
        st.info("No confirmed posts matched all filters. Check the 'Needs Review' section.")

    st.divider()
    excel_bytes = exporter.to_excel_bytes(confirmed, review)
    st.download_button(
        label="📥 Download Excel",
        data=excel_bytes,
        file_name=exporter.output_filename(),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
elif st.session_state.get("confirmed") is not None:
    st.info(
        "No confirmed posts found. "
        "If you uploaded a saved page, check that it contains recruiter posts "
        "that **explicitly share an HR email address** in the post text "
        "(e.g. *\u2018Send CV to hr@company.com\u2019*). "
        "Job-board aggregator posts (Protocol Jobs, LinkedIn Jobs, etc.) rarely include "
        "direct email addresses and will always be filtered out when the email toggle is on."
    )
