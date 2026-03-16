# FACEFIELD

Web photo ingestion + face grouping prototype built with FastAPI, Jinja templates, SQLite, FAISS, Playwright, and InsightFace.

## Features
- Scrape image URLs from a page with Playwright
- Optional preview page screenshot before ingest
- Download and process images (including `data:image/...` URLs)
- Detect faces and generate embeddings with InsightFace
- Group faces into people using FAISS cosine similarity search
- Browse people and person detail pages
- Admin action to clear person/face data
- Social ingestion API for account interaction graph captures
- Social account search + ego-network API/UI
- Firefox extension for manual Facebook comment/reply/mention capture

## Tech Stack
- FastAPI + Jinja2 templates
- SQLAlchemy + SQLite
- FAISS (`IndexFlatIP`)
- InsightFace
- Playwright

## Repository Layout
```text
app.py
database.py
models.py
scraper.py
face_engine.py
requirements.txt
templates/
static/
images/
faces/
previews/
faiss_index/
extension/
```

## Installation
### 1. Clone
```bash
git clone https://github.com/bbreisch26/facefield.git
cd facefield
```

### 2. Create and activate virtual environment
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright browser binaries
```bash
playwright install
```

## Run
```bash
uvicorn app:app --reload
```

Open:
- http://localhost:8000
- http://localhost:8000/social

## Usage
1. Go to `/`.
2. Paste a page URL.
3. Click `Preview Page` to see what Playwright sees, or click `Ingest` directly.
4. Open `/people` to view detected people.
5. Open `/admin` for maintenance actions.

## Notes
- Data is stored in `app.db`.
- Downloaded images are stored under `images/`.
- Face crops are stored under `faces/`.
- FAISS index is stored under `faiss_index/index.bin`.
- Set `SOCIAL_API_KEY` before using `POST /api/social/captures`.

## Social Capture API
- `POST /api/social/captures` with header `X-API-Key`
- `GET /api/social/accounts/search?q=<term>&platform=<facebook|instagram|x>`
- `GET /api/social/accounts/{id}/ego?direction=<in|out|both>&type=<comment|reply|mention>`

## Firefox Extension
- Extension source is in `extension/firefox/`.
- Load the extension in Firefox from `manifest.json`.
- Configure backend URL and API key in extension options.
- Open a Facebook page/post and click `Capture Current Page`.

## Troubleshooting
- If Playwright fails to launch, re-run `playwright install`.
- If face detection fails at runtime, verify InsightFace model dependencies are installed correctly in your environment.
