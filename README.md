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
```

## Installation
### 1. Clone
```bash
git clone <your-repo-url>.git
cd <your-repo-folder>
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

## Troubleshooting
- If Playwright fails to launch, re-run `playwright install`.
- If face detection fails at runtime, verify InsightFace model dependencies are installed correctly in your environment.
