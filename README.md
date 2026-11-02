# FINN — Financial Investment Agent

**Detect → Prioritize → Investigate**  
A mobile-first investment intelligence prototype for monitoring NSE portfolio companies and researching their disclosures using traceable primary sources.

> **Live demo:** [Open FINN](https://finn-investment-intelligence.vercel.app/) · **API:** [Backend health](https://finn-fastapi.onrender.com/health) · **Source:** [GitHub](https://github.com/bipin98kumarjaiswal/FINN-Investment-Intelligence)  
> The deployed demo uses a **dated, verified snapshot** rather than a continuously updated or live intraday feed. To see stored announcements, choose **7 days** if the default **24 hours** is empty.

## Why FINN exists

Investors already have access to prices, exchange announcements, and company reports. The harder problem is **deciding what deserves attention** and then finding reliable evidence to investigate it. FINN puts those tasks in one workflow:

1. **Detect** — monitor genuine exchange announcements and end-of-day (EOD) price/volume records for a 16-company NSE portfolio.
2. **Prioritize** — separate material events from routine filings using explainable rules and selective analysis of PDF attachments.
3. **Investigate** — open the original filing or research a company through indexed annual reports, earnings-call transcripts, and financial results with page-linked citations.

The product is intended as a **decision-support and research tool**, not a trading system, price predictor, or investment recommendation engine.

## What is implemented

| Area | Working functionality |
| --- | --- |
| **Today / Push** | Default 24-hour filing briefing; 7-/30-day and custom windows; High/Review items ranked first; routine filings collapsed; original NSE attachment links and priority explanations. |
| **Document-aware prioritization** | Metadata screening for every retrieved filing; eligible filings receive bounded PDF text analysis with excerpts, page numbers, score components, and cached extraction. |
| **Alerts** | Configurable EOD percentage-change, volume-spike and filing-category criteria; derived alert history from stored price and filing records. |
| **Portfolio** | Latest stored close, dated price history, and traded volume for 16 NSE-listed companies. |
| **Research / Pull** | NSE ticker search beyond the demo portfolio; discovery or addition of supported primary PDFs; indexed passages; questions answered using only retrieved document excerpts with source links. |
| **Guidance vs. actual** | Conservative comparison attempt when a dated prior guidance statement and subsequently published, like-for-like result can be verified. Otherwise returns **insufficient evidence**. |
| **Deployment** | React/Vite on Vercel; FastAPI on Render Free; verified SQLite snapshot restored from a separate private GitHub repository on each fresh Render process start. |

### Demonstration data

The deployment snapshot was prepared from **real source records**, not generated financial examples. The snapshot audit recorded **16 companies with prices, 1,024 daily OHLCV records, 108 NSE announcements, 3 Infosys primary-source PDFs, and 3,263 indexed passages**. Counts describe the particular verified snapshot, not a guarantee of current live coverage. The latest stored market session in the tested portfolio was **30 October 2026**. The deployed UI may show an empty 24-hour briefing when the snapshot contains no announcements in that window; select a longer period to inspect historical filings.

## Architecture

```text
                         Mobile-first React / Vite
                          hosted on Vercel
                                 |
                      /api/* rewrite to Render
                                 |
                        FastAPI REST backend
                           hosted on Render
                     ____________|____________
                    |                         |
              Push services              Pull services
        NSE announcements +          NSE ticker catalog +
        price/volume ingestion       primary PDF ingestion
                    |                         |
        metadata classification      page-aware extraction
        selective NSE PDF scoring    + SQLite FTS5 search
        EOD / filing alert rules     + optional Gemini synthesis
                    |                         |
                    +-----------+-------------+
                                |
                          SQLite working DB
             prices · filings · PDF cache · research passages
                                ^
                          verified restore
                                |
          Private GitHub SQLite snapshot (separate private repo)
```

**Main technologies:** React 19, Vite, Tailwind CSS, FastAPI, Python, SQLite/FTS5, `yfinance`, `requests`, PyMuPDF, and the optional Gemini API. The backend uses direct library integrations and small Python modules rather than an agent orchestration framework, vector database, or multi-service queue.

### Repository structure

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI, portfolio, briefing, alerts
│   │   ├── portfolio.py            # 16-company NSE demo portfolio
│   │   ├── market_data.py          # Yahoo EOD OHLCV ingestion
│   │   ├── nse_filings.py          # NSE announcement ingestion
│   │   ├── classifier.py           # metadata classification and scores
│   │   ├── pdf_priority.py         # selective NSE PDF analysis + cache
│   │   ├── alerts.py               # EOD and filing alert calculations
│   │   ├── database.py             # SQLite schema and queries
│   │   ├── research_catalog.py     # NSE ticker catalog
│   │   ├── research_pdf.py         # bounded, verified PDF ingestion
│   │   ├── research_store.py       # SQLite FTS5 index
│   │   ├── research_service.py     # retrieval and guidance validation
│   │   ├── research_ai.py          # optional Gemini synthesis
│   │   └── research_api.py         # research endpoints
│   ├── scripts/
│   │   ├── seed_infosys_research.py
│   │   ├── demo_snapshot.py       # private GitHub snapshot restore
│   │   └── serve_demo.py          # restore first, then start API
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/                # Today, Alerts, Portfolio, Research
│   │   ├── components/           # filing detail + citations
│   │   └── lib/                  # API client and formatting
│   ├── vercel.json               # /api rewrite to Render
│   └── package.json
└── README.md
```

> Some deployment-verification helpers were supplied separately in the deployment kit. If you include `deploy/verify_public_demo.py` in your public repository, keep only code; do not include its private baseline JSON or any credentials.

## Data sources and evidence handling

| Source | Used for | Notes |
| --- | --- | --- |
| [Yahoo Finance](https://finance.yahoo.com/) through `yfinance` | NSE EOD open/high/low/close and trading volume (`.NS` symbols) | Unofficial programmatic access; data can be delayed, revised, rate-limited, or unavailable. |
| [NSE corporate announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) | Exchange filing metadata and original attachments | The filing URL, exchange-provided subject, description, and publication date are retained. An endpoint request may fail or return no records. |
| [Infosys investor relations](https://www.infosys.com/investors/reports-filings/) | Annual report, quarterly results, earnings-call transcript | Official primary documents indexed for the source-grounded research demonstration. |
| Other verified primary-source PDF URLs | Broader ticker research where documents are available | Coverage depends on official-source availability and the backend's trusted-host policy. |

**Primary sources are essential to Pull.** FINN does not rely on broker reports, news summaries, or an LLM's unaided memory to establish company facts. Research results point to a document title, source URL, page, and excerpt; unavailable evidence is reported rather than invented.

### Two-stage filing priority (Push)

**Stage 1 — inexpensive metadata screening.** All retrieved filings are categorised from the NSE subject/description using the reference categories (results, M&A, management change, credit rating, litigation, etc.) and concrete event language. This creates a traceable score and explanation.

**Stage 2 — selective PDF analysis.** Only potentially relevant filings (**metadata score ≥ 40**) qualify for original NSE PDF examination. Selectable text is extracted and cached. Supported document signals contribute bounded adjustments (**−20 to +30 points**), with a PDF page and excerpt when applicable.

| Final score | Display label |
| --- | --- |
| 70–100 | **High** |
| 40–69 | **Review** |
| 0–39 | **Routine** |

The filing detail exposes the initial score, additions/deductions, cap if applied, resulting label, and source evidence. A regression fix prevents table headings such as **“Net Profit/Loss after tax”** from being misclassified as an actual reported loss. A loss signal requires stronger affirmative, quantified context. These are **review-priority heuristics**, not estimated economic impact or future return predictions.

For the filing-priority pass, documents over **12 MiB**, over **150 pages**, or without usable selectable text are not silently considered analysed. An oversized file is marked `skipped_too_large`, retains its metadata-based score and original filing URL, and is not repeatedly downloaded. The separate Pull document processor has its own **28 MiB / 450-page** cap.

### Briefing and alerts (Push)

- The briefing defaults to a rolling **24-hour** window; users can choose other windows, including custom dates.
- High and Review filings appear first, and routine disclosures are collapsed but accessible.
- Filing cards show the exchange-reported event, why it merits review, and a direct link to the original filing. The PDF analysis status is visible if full attachment analysis did not run.
- Price-movement alerts compare consecutive EOD closes; volume alerts compare daily volume with a configurable previous-session average (default **20 sessions**). Users can change price thresholds, volume multiples, and selected filing categories.
- Alerts are **evaluated from stored EOD/filing records**. They are not real-time intraday alerts or push notifications delivered to an external device.

### Document-grounded research (Pull)

1. Search a company ticker using the NSE equity catalog; search is not restricted to the 16 holdings.
2. Discover suitable NSE document attachments or add an approved, verified primary PDF URL.
3. Download the PDF with source-host restrictions and size limits, extract selectable text, split into page-aware passages, and index it with **SQLite FTS5**.
4. Retrieve relevant passages for the question. With `GEMINI_API_KEY`, ask Gemini to select relevant quotations from **only these excerpts**, using source IDs such as `[S1]`; verify each quotation against the retrieved passage before displaying it. Otherwise display the source passages directly.
5. Return the supporting excerpts, document references and pages alongside the response.

The backend checks that source IDs correspond to retrieved passages and verifies proposed quotations against their cited text. If quotation verification fails, it returns original evidence excerpts instead of an unverified generated answer. **Matching citations and quotations do not establish that every wider interpretation is semantically correct.** Users should inspect the linked original source.

**Management guidance vs actual:** the comparison endpoint is intentionally strict. It requires a guidance statement published **before** the relevant period ends and subsequent actual results for the **same metric, fiscal period, units, and reporting basis**. A current-quarter result is not substituted for annual actuals. If a matching, documented pair is missing, FINN returns `insufficient_evidence`. The feature is **conditional**, not a general-purpose verified forecast scorecard for every company.

## Run locally

### Requirements

- Python **3.10+** (Python 3.11 recommended)
- Node.js compatible with the installed Vite version (Vite 7 requires **20.19+ or 22.12+**)
- Internet access for source ingestion, NSE catalog refresh and Gemini requests
- A Gemini API key **only if** you want generated, cited responses (extractive research works without it)

### 1. Start the backend

From the repository root, in PowerShell:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8000
```

The API docs are at `http://127.0.0.1:8000/docs`; the health endpoint is `/health`. On an empty local database, portfolio rows may have `null` prices until you sync real data.

To enable AI synthesis, set `GEMINI_API_KEY` **in the backend environment** before launching the API; `FINN_GEMINI_MODEL` optionally selects the model. Never put these in Vite or public Git files.

### 2. Load genuine data (separate backend terminal)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.sync --period 3mo
python -m app.filings_sync --days 14 --analyze-important --max-pdfs 5
python -m app.alerts_sync
python -m app.research_catalog --refresh
python -m scripts.seed_infosys_research
```

Each source command has its own status and possible network failure. No mock prices, announcements, or research passages are silently injected into the real database. For a different company's documents, use the Research UI with approved primary PDF URLs; verify additional company-owned IR domains before configuring `FINN_TRUSTED_IR_HOSTS`.

### 3. Start the frontend (another terminal)

```powershell
cd frontend
npm install
npm test
npm run build
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the locally running FastAPI backend. With that backend running, also use `npm run smoke:api` for basic API compatibility checks.

### Linux/macOS backend equivalent

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8000
```

## Deployment: Vercel + Render Free + verified private snapshot

The app's deployed instance uses **Vercel for the React frontend** and **Render Free for FastAPI**. Vercel's `frontend/vercel.json` rewrites `/api/*` to the Render HTTPS service. The deployed React interface is served by Vercel. The API key and GitHub snapshot token stay on Render; neither is exposed as a frontend environment variable.

### Why restore a snapshot?

**Render Free does not provide durable filesystem storage.** A fresh instance or redeployment can lose a locally written SQLite database. Simply deploying the API would risk a healthy `/health` response with an **empty** portfolio, announcement feed, or research index. We therefore use a **separate private GitHub repository containing a previously audited SQLite snapshot**. This restores a reproducible demonstration without requiring a paid database service.

The snapshot is a **fixed point-in-time dataset**; this is not continuous market synchronization, persistent user storage, or an automatic snapshot-backup service. Runtime changes to alert preferences or other data on the Render instance are **ephemeral** and reset when a new working copy is restored.

### Render startup sequence

```text
Render process starts: python -m scripts.serve_demo
  → download raw SQLite bytes via authenticated GitHub Contents API
  → check SHA-256 matches the pinned expected snapshot
  → verify SQLite integrity and required prices, filings, research records/FTS
  → atomically install writable working copy at /tmp/finn-demo/finn.sqlite3
  → start FastAPI on Render's provided PORT
```

Download uses a **fine-grained GitHub token with Contents: Read-only**, restricted to the separate private snapshot repository, and GitHub's raw-content response for a multi-megabyte file. The restore code does not forward the token to arbitrary redirect hosts, and a mismatched checksum or missing required records blocks startup rather than starting with empty data. The token is **never** committed or sent to the browser.

**Render configuration (set values privately in the Render dashboard):**

| Variable | Purpose |
| --- | --- |
| `FINN_DB_PATH` | Runtime database path selected by the restore startup script (for this demo, `/tmp/finn-demo/finn.sqlite3`) |
| `FINN_GITHUB_OWNER` | Private snapshot repository owner |
| `FINN_GITHUB_REPO` | Private snapshot repository name |
| `FINN_GITHUB_PATH` | SQLite object path inside that private repo |
| `FINN_GITHUB_REF` | Pinned commit SHA (recommended) |
| `FINN_GITHUB_TOKEN` | Private read-only Contents token |
| `FINN_SNAPSHOT_SHA256` | Expected full-file SHA-256 |
| `GEMINI_API_KEY` | Optional server-side research model key |
| `FINN_GEMINI_MODEL` | Optional model identifier |

Render service settings: root `backend`, build command `pip install -r requirements.txt`, start command **`python -m scripts.serve_demo`**, and the platform-provided `PORT`.

Vercel settings: root `frontend`, framework Vite, build command `npm run build`, output directory `dist`. The committed `frontend/vercel.json` points to `https://finn-fastapi.onrender.com` and must remain valid if the backend URL changes.

**How to verify recovery:** query the public API for all 16 priced companies, actual filing records, indexed Infosys documents and a cited `/api/research/ask` answer. Repeat after a fresh Render restart and confirm the underlying record fingerprints agree. The deployment kit includes `deploy/verify_public_demo.py` for before/after comparison. Store its baseline outside the public Git repository. A successful `/health` alone is not sufficient evidence that the snapshot was restored.

See [Render Free limitations](https://render.com/docs/free), [GitHub Contents API](https://docs.github.com/en/rest/repos/contents), and [Vercel rewrites](https://vercel.com/docs/routing/rewrites).

## API overview

| Endpoint | Description |
| --- | --- |
| `GET /health` | Process availability (not a live-data freshness guarantee) |
| `GET /api/portfolio` | Portfolio and latest stored EOD prices |
| `GET /api/prices/{symbol}` | Stored OHLCV history |
| `GET /api/briefing?hours=168` | Time-windowed ranked NSE briefing |
| `GET /api/announcements/{filing_id}` | Filing detail, score breakdown and sources |
| `GET /api/filings/status` | Filing sync results/errors |
| `GET /api/alerts` | Derived alerts |
| `GET /api/preferences/alerts` | Alert preferences |
| `PUT /api/preferences/alerts` | Update preferences and recalculate derived alerts |
| `GET /api/research/search?q=INFY` | NSE ticker search |
| `GET /api/research/INFY/documents` | Indexed documents |
| `GET /api/research/INFY/candidates?days=90` | Discover recent NSE document candidates |
| `POST /api/research/ask` | Primary-source-grounded question-answering |
| `POST /api/research/guidance` | Conditional guidance comparison |

The autogenerated FastAPI endpoint documentation is available at `/docs` on the backend.

## Tests and demonstrated behavior

The project includes Python tests for persistence, API responses, NSE parsing, classification, PDF caching and scoring, alert calculations, citation handling, and period-matched guidance checks; frontend utility and API smoke tests are also included. The development history reports a **64-test passing suite** at final integration; the full backend suite was reported as **64 passed, 1 non-blocking deprecation warning** after the snapshot patch; rerun on the submitted commit if any code changes.

The deployed workflows were manually exercised: the mobile briefing displayed real NSE filings and priority breakdowns; the portfolio showed stored real prices for all 16 companies; configurable alerts worked; and Infosys research returned document references. The startup snapshot was audited prior to deployment, and a deployed portfolio request returned 16 companies with dated, non-null prices. A controlled restart comparison has not yet been independently recorded here. Do not interpret these checks as continuous uptime guarantees, unlimited ticker/document coverage, or evidence that every possible generated statement has been independently verified.

## Known limitations and trade-offs

1. **Dated demo, not a continuously updated feed:** the Render deployment restores a fixed verified snapshot. The default last-24-hours view can be empty as that snapshot ages. Live fetching is available through local ingestion scripts, not automatically scheduled in the deployed Free instance.
2. **EOD, not intraday:** alerts use stored daily bars and evaluated filing records; there is no live market tick stream, mobile push delivery, or price-movement forecasting.
3. **Heuristic priority:** document-aware scoring uses explainable patterns, not a trained model of market impact. Transaction-size/valuation comparisons and complex financial tables are not comprehensively analysed.
4. **Source availability:** NSE responses can be throttled or blocked; some exchange/IR PDFs are oversized, scanned, badly formatted, or absent. Skipped analysis is labelled; an inaccessible source does not become a fabricated fact.
5. **Research coverage varies:** only ingested, supported primary PDFs are searchable. NSE ticker search generalises, but it does not mean every listed company has a full research library.
6. **Citation limitations:** source IDs, excerpts and pages are preserved, but a valid citation alone cannot prove that an LLM interpretation is correct. Model outages yield evidence-only or error states, not an invented answer.
7. **Guidance comparison is conditional:** the system often reports insufficient evidence, particularly when dated, same-period guidance and actual results cannot both be established.
8. **Prototype security and durability:** no production-grade authentication, per-user access control or persistent user preferences. The source-ingestion API needs authentication, rate limits and broader security hardening before public multi-user use. Free-service cold starts can delay the first request.

## Engineering decisions

- **Rules first, AI when helpful:** deterministic market calculations and filing filters are cheaper, faster and easier to audit; the model only synthesises retrieved document evidence.
- **Selective PDF extraction:** avoids downloading and parsing routine paperwork; caching also avoids repeated work.
- **SQLite + FTS5:** sufficient for this small portfolio and document corpus; avoids maintaining a vector database or extra services for the prototype.
- **Fail visibly:** empty or stale source results, oversized documents, unsupported comparisons, and missing citations are explicitly surfaced instead of hidden.
- **Portable, reproducible demo:** a pinned, checksum-verified private snapshot lets the Free service start with consistent real data, at the cost of non-durable runtime edits and no automatic refresh.

## What I would build next

Persistent hosted storage and background refresh jobs; authenticated multi-user alert settings; wider primary-document coverage and better table parsing; deeper numeric comparison of corporate events; more thorough sentence-level answer verification; and evaluated guidance-versus-actual case studies using confirmed historical pairs. These are **future work**, not current capabilities.

---

**Disclaimer:** FINN is an engineering demonstration for research and information organisation. It is not investment advice, an execution platform, or a real-time market-data service.
