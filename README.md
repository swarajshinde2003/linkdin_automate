
# PYTHON VERSION == 3.12.9

# LinkedIn Hiring Post Agent

A free, local AI agent that finds recruiter/person hiring posts on LinkedIn, extracts job details (role, company, location, experience, HR email, post link), filters by recency (last 24 hours), and exports a styled Excel sheet — no paid API required.

---

## What it does

1. You enter keywords like `genai`, `hiring`, `pune`
2. The app generates a LinkedIn search URL for you to open manually
3. You paste post text, upload a saved HTML page, or provide post URLs
4. The agent extracts: **role · company · location · experience · HR email · post link · timestamp**
5. Posts are filtered (keyword match + hiring signal + last 24 h + has email)
6. Results download as a `.xlsx` Excel file with two sheets:
   - **Hiring Posts** — confirmed, ranked by recency
   - **Needs Review** — missing timestamp or email

---

## Project structure

```
linkdin_automate/
├── app.py                  ← Streamlit UI entry point
├── requirements.txt        ← Python dependencies
├── .env                    ← Local config (not committed)
└── src/
    ├── __init__.py
    ├── models.py           ← HiringPost Pydantic model
    ├── collectors.py       ← Paste / HTML / URL input parsers + image extraction
    ├── extractor.py        ← Three-tier extraction (Remote LLM → Ollama → Rules)
    ├── filters.py          ← Keyword, recency, email, dedup, ranking
    └── exporter.py         ← Excel export with styled columns
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | `python --version` to check |
| Git | Already set up if you cloned this repo |
| Ollama (optional) | For local LLM extraction — see below |
| Remote gpt-4o model (optional) | LM Studio or any OpenAI-compatible server at `http://192.168.1.124:4141/v1` |

---

## Setup

### 1. Clone / open the project

```powershell
cd F:\Git_gen_ai_project\linkdin_automate
```

### 2. Create and activate the virtual environment

```powershell
python -m venv linkdin_env
.\linkdin_env\Scripts\Activate.ps1
```

> On first run you may need to allow script execution:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure `.env`

The `.env` file is already pre-filled. Edit it if your setup differs:

```env
# Local Ollama (optional — install from https://ollama.com)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# App behaviour
LOOKBACK_HOURS=24
MAX_POSTS=500

# Remote OpenAI-compatible model — priority over Ollama when reachable
# Leave REMOTE_LLM_BASE_URL blank to use Ollama only
REMOTE_LLM_BASE_URL=http://192.168.1.124:4141/v1
REMOTE_LLM_API_KEY=NO_API_KEY
REMOTE_LLM_MODEL=gpt-4o
```

### 5. (Optional) Set up Ollama for local LLM extraction

```powershell
# Download Ollama from https://ollama.com and install, then:
ollama pull llama3
```

---

## Run the app

```powershell
# Make sure the virtual env is active
.\linkdin_env\Scripts\Activate.ps1

streamlit run app.py
```

The app opens at **http://localhost:8501** in your browser.

---

## How to use the app

### Step 1 — Set keywords and filters (sidebar)

| Setting | Example | Description |
|---|---|---|
| Keywords | `genai, hiring, pune` | Comma-separated; matched against post text |
| Keyword mode | `any` / `all` | `any` = at least one keyword; `all` = every keyword |
| Lookback window | `24` hours | Posts older than this are discarded |
| Only posts with HR email | ✅ checked | Uncheck to also keep posts without an email |

### Step 2 — Open LinkedIn search manually

Click the **"Open in LinkedIn ↗"** link in the sidebar. This opens a LinkedIn search pre-filled with your keywords, sorted by date. Browse and collect post content.

> LinkedIn requires login to see full post content. The app does **not** automate login or bypass any authentication.

### Step 3 — Provide LinkedIn content (pick one tab)

| Tab | How to use |
|---|---|
| **Paste Text** | Copy one or multiple post texts from LinkedIn and paste them. Separate posts with blank lines. |
| **Upload HTML** | In your browser: `Ctrl+S` → save as *Webpage, HTML Only*. Upload the `.html` file. Images in the page are also extracted for OCR. |
| **Post URLs** | Paste LinkedIn post URLs (one per line). Publicly accessible posts are fetched automatically; auth-required ones are flagged. |

### Step 4 — Analyse

Click **🚀 Analyse Posts**. The agent will:
- Run regex rules to extract emails and timestamps (always)
- Call the remote gpt-4o model if reachable (extracts role, company, location, experience + **OCR on images**)
- Fall back to local Ollama if the remote model is unavailable
- Apply keyword, recency, email, and deduplication filters
- Rank results by newest → has email → keyword coverage

### Step 5 — Download Excel

Click **📥 Download Excel** to save `linkedin_hiring_YYYYMMDD_HHMMSS.xlsx`.

---

## Excel output columns

### Sheet 1 — Hiring Posts

| Column | Description |
|---|---|
| `role` | Job title extracted from post |
| `company` | Hiring company name |
| `location` | City / state |
| `experience` | Years of experience required (e.g. "3-5 years", "5+ yrs") |
| `hr_mail` | Recruiter / HR email address |
| `post_link` | LinkedIn post URL |
| `posted_at` | ISO timestamp or relative time parsed from post |
| `confidence` | Extraction confidence score (0.0 – 1.0) |
| `matched_keywords` | Which of your keywords were found |
| `source` | Input method: `paste` / `html` / `url` |

### Sheet 2 — Needs Review

Same columns plus `needs_review` flag and `raw_text` snippet (first 500 chars) for posts where timestamp or email was missing.

---

## LLM extraction tiers

The extractor tries models in this order and uses the first that responds:

| Tier | Model | Condition | Capabilities |
|---|---|---|---|
| **1 — Remote** | `gpt-4o` at `192.168.1.124:4141` | `REMOTE_LLM_BASE_URL` set and reachable | Text extraction + **image OCR / vision** |
| **2 — Ollama** | `llama3` at `localhost:11434` | Ollama running locally | Text extraction only |
| **3 — Rules** | Regex only | Always active as baseline | Email regex, URL regex, timestamp scanning |

The app works fully with Rules-only mode. Each higher tier improves role/company/location/experience accuracy.

---

## Filtering logic

A post is **confirmed** if it passes all of these:

1. Contains at least one (or all, based on mode) of your keywords
2. Contains a hiring-intent signal: `hiring`, `urgent requirement`, `opening`, `send cv`, `share resume`, `dm me`, etc.
3. Has a detectable timestamp within the lookback window
4. Has an HR email (if "Only posts with HR email" is checked)

Posts that pass keywords/signal but fail timestamp or email go into the **Needs Review** sheet.

---

## Deduplication and ranking

Posts are deduplicated by the combination of `hr_mail + role + location + post_link`.

Confirmed posts are ranked by:
1. Newest `posted_at` first
2. Has HR email
3. Most keyword matches
4. Highest confidence score

---

## Limitations and notes

- **LinkedIn ToS**: This app does not automate LinkedIn login, bypass CAPTCHA, or perform headless scraping. You manually browse LinkedIn and provide content to the app.
- **Timestamp accuracy**: LinkedIn often shows relative times ("2 hours ago"). The app parses these, but exact timestamps require saving the HTML before the page is refreshed.
- **Image OCR**: Only available when the remote gpt-4o model is reachable. Inline base64 images and LinkedIn CDN image URLs from saved HTML are supported.
- **Role/experience accuracy**: In rules-only mode these fields will be empty. LLM tiers fill them in.
- **Free tier**: Everything runs locally. No paid API keys are required. The remote model at `192.168.1.124:4141` is assumed to be your own LM Studio or compatible server.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `streamlit: command not found` | Run `pip install streamlit` inside the activated virtual env |
| Remote model shows as unreachable | Check that LM Studio / your server is running and `REMOTE_LLM_BASE_URL` in `.env` is correct |
| Ollama shows as unreachable | Run `ollama serve` in a separate terminal, or install from https://ollama.com |
| No confirmed posts found | Try unchecking "Only posts with HR email", or widen the lookback window |
| HTML upload parses 0 blocks | Save the page as *Webpage, HTML Only* (not *Complete*); LinkedIn single-post pages work best |
| Posts appear in Needs Review only | The post text has no parseable timestamp — manually note the date or widen the lookback window |
