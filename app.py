import base64
import binascii
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4
from urllib.parse import unquote_to_bytes, urlparse

import faiss
import numpy as np
import requests
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased

from database import SessionLocal, init_db
from face_engine import process_image
from models import Face, Image, Person, SocialAccount, SocialCaptureRaw, SocialContent, SocialInteraction
from scraper import scrape_images, scrape_images_with_preview
from social_graph import (
    CaptureBatch,
    INTERACTION_TYPES,
    SUPPORTED_PLATFORMS,
    query_ego_network,
    validate_api_key,
    ingest_capture_batch,
    normalize_platform,
)

SIMILARITY_THRESHOLD = 0.50
FAISS_INDEX_PATH = Path("faiss_index/index.bin")
PEOPLE_PER_PAGE = 30
SOCIAL_API_KEY_ENV = "SOCIAL_API_KEY"


class FaceMatcher:
    def __init__(self, threshold: float = SIMILARITY_THRESHOLD):
        self.threshold = threshold
        self.index: Optional[faiss.IndexFlatIP] = None
        self.face_ids: List[int] = []

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        vec = np.array(vector, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(vec)
        return vec

    def load_from_db(self, db: Session) -> None:
        rows = db.query(Face.id, Face.embedding).order_by(Face.id.asc()).all()

        if not rows:
            self.index = None
            self.face_ids = []
            return

        vectors: List[np.ndarray] = []
        face_ids: List[int] = []
        for face_id, emb_blob in rows:
            vec = np.frombuffer(emb_blob, dtype=np.float32)
            if vec.size == 0:
                continue
            vectors.append(vec)
            face_ids.append(face_id)

        if not vectors:
            self.index = None
            self.face_ids = []
            return

        matrix = np.vstack(vectors).astype(np.float32)
        faiss.normalize_L2(matrix)

        self.index = faiss.IndexFlatIP(matrix.shape[1])
        self.index.add(matrix)
        self.face_ids = face_ids

        self.save()

    def save(self) -> None:
        if self.index is None:
            return
        FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(FAISS_INDEX_PATH))

    def add(self, face_id: int, embedding: np.ndarray) -> None:
        vec = self._normalize(embedding)
        if self.index is None:
            self.index = faiss.IndexFlatIP(vec.shape[1])
        self.index.add(vec)
        self.face_ids.append(face_id)

    def find_best_face_id(self, embedding: np.ndarray) -> Optional[int]:
        if self.index is None or self.index.ntotal == 0:
            return None

        vec = self._normalize(embedding)
        scores, indices = self.index.search(vec, 100)
        top_score = float(scores[0][0])
        top_idx = int(indices[0][0])
        print(scores)
        if top_idx < 0 or top_score < self.threshold:
            return None

        return self.face_ids[top_idx]

    def reset(self) -> None:
        self.index = None
        self.face_ids = []
        if FAISS_INDEX_PATH.exists():
            FAISS_INDEX_PATH.unlink()


app = FastAPI(title="FACEFIELD")
templates = Jinja2Templates(directory="templates")
matcher = FaceMatcher()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/images", StaticFiles(directory="images"), name="images")
app.mount("/faces", StaticFiles(directory="faces"), name="faces")
app.mount("/previews", StaticFiles(directory="previews"), name="previews")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_social_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv(SOCIAL_API_KEY_ENV, "").strip()
    try:
        validate_api_key(provided_key=x_api_key, expected_key=expected)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def ensure_directories() -> None:
    for folder in ["images", "faces", "faiss_index", "previews"]:
        Path(folder).mkdir(parents=True, exist_ok=True)


def get_extension(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return suffix

    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    if "gif" in content_type:
        return ".gif"
    if "bmp" in content_type:
        return ".bmp"
    return ".jpg"


def download_image(source_url: str) -> Optional[str]:
    if source_url.startswith("data:image/"):
        return download_data_image(source_url)

    try:
        resp = requests.get(source_url, timeout=10)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "").lower()
        ext = get_extension(source_url, content_type)
        filename = f"{uuid4().hex}{ext}"
        out_path = Path("images") / filename
        out_path.write_bytes(resp.content)
        return filename
    except Exception:
        return None


def download_data_image(source_url: str) -> Optional[str]:
    try:
        header, payload = source_url.split(",", 1)
    except ValueError:
        return None

    meta = header[5:]  # strip "data:"
    if not meta.startswith("image/"):
        return None

    mime = meta.split(";")[0].lower()
    if "png" in mime:
        ext = ".png"
    elif "jpeg" in mime or "jpg" in mime:
        ext = ".jpg"
    elif "webp" in mime:
        ext = ".webp"
    elif "gif" in mime:
        ext = ".gif"
    elif "bmp" in mime:
        ext = ".bmp"
    else:
        ext = ".jpg"

    try:
        if ";base64" in meta:
            data = base64.b64decode(payload, validate=True)
        else:
            data = unquote_to_bytes(payload)
    except (ValueError, binascii.Error):
        return None

    if not data:
        return None

    filename = f"{uuid4().hex}{ext}"
    out_path = Path("images") / filename
    out_path.write_bytes(data)
    return filename


def find_or_create_person(db: Session, embedding: np.ndarray) -> Tuple[Person, Optional[int]]:
    matched_face_id = matcher.find_best_face_id(embedding)

    if matched_face_id is None:
        person = Person()
        db.add(person)
        db.flush()
        return person, None

    matched_face = db.query(Face).filter(Face.id == matched_face_id).first()
    if matched_face is None:
        person = Person()
        db.add(person)
        db.flush()
        return person, None

    person = db.query(Person).filter(Person.id == matched_face.person_id).first()
    if person is None:
        person = Person()
        db.add(person)
        db.flush()

    return person, matched_face_id


@app.on_event("startup")
def startup_event() -> None:
    ensure_directories()
    init_db()
    db = SessionLocal()
    try:
        matcher.load_from_db(db)
    finally:
        db.close()


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/ingest")
def ingest(url: str = Form(...), db: Session = Depends(get_db)):
    image_urls = scrape_images(url)

    for image_url in image_urls:
        filename = download_image(image_url)
        if not filename:
            continue

        image_row = Image(
            ingest_page_url=url,
            source_url=image_url,
            file_path=filename,
            contains_person=False,
        )
        db.add(image_row)
        db.flush()

        image_path = str(Path("images") / filename)
        try:
            faces_found = process_image(image_path)
        except Exception:
            continue

        if not faces_found:
            image_row.contains_person = False
            continue

        image_row.contains_person = True

        for face_data in faces_found:
            embedding = face_data["embedding"].astype(np.float32)
            person, _ = find_or_create_person(db, embedding)

            face_row = Face(
                image_id=image_row.id,
                person_id=person.id,
                embedding=embedding.tobytes(),
                face_path=face_data["face_crop_path"],
            )
            db.add(face_row)
            db.flush()

            matcher.add(face_row.id, embedding)

    db.commit()
    matcher.save()

    return RedirectResponse(url="/people", status_code=303)


@app.post("/preview")
def preview(request: Request, url: str = Form(...)):
    try:
        image_urls, preview_filename = scrape_images_with_preview(url)
        sample_urls = sorted(image_urls)[:24]
        return templates.TemplateResponse(
            "ingest_status.html",
            {
                "request": request,
                "url": url,
                "preview_image": preview_filename,
                "image_count": len(image_urls),
                "sample_urls": sample_urls,
                "message": f"Playwright loaded this page and found {len(image_urls)} image URL(s).",
            },
        )
    except Exception:
        return templates.TemplateResponse(
            "ingest_status.html",
            {
                "request": request,
                "url": url,
                "preview_image": None,
                "image_count": 0,
                "sample_urls": [],
                "message": "Preview failed while loading this URL with Playwright.",
            },
        )


@app.get("/people")
def people(request: Request, page: int = 1, db: Session = Depends(get_db)):
    page = max(1, page)
    offset = (page - 1) * PEOPLE_PER_PAGE

    total_people = db.query(func.count(Person.id)).scalar() or 0
    total_pages = max(1, (total_people + PEOPLE_PER_PAGE - 1) // PEOPLE_PER_PAGE)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * PEOPLE_PER_PAGE

    rows = (
        db.query(Person.id, func.count(Face.id).label("face_count"))
        .outerjoin(Face, Face.person_id == Person.id)
        .group_by(Person.id)
        .order_by(func.count(Face.id).desc(), Person.id.asc())
        .offset(offset)
        .limit(PEOPLE_PER_PAGE)
        .all()
    )

    preview_by_person: Dict[int, str] = {}
    person_ids = [row.id for row in rows]
    if person_ids:
        first_face_subq = (
            db.query(
                Face.person_id.label("person_id"),
                func.min(Face.id).label("first_face_id"),
            )
            .filter(Face.person_id.in_(person_ids))
            .group_by(Face.person_id)
            .subquery()
        )
        preview_rows = (
            db.query(Face.person_id, Face.face_path)
            .join(first_face_subq, Face.id == first_face_subq.c.first_face_id)
            .all()
        )
        preview_by_person = {row.person_id: row.face_path for row in preview_rows}

    people_data: List[Dict] = [
        {
            "id": row.id,
            "face_count": row.face_count,
            "preview_face_path": preview_by_person.get(row.id),
        }
        for row in rows
    ]

    return templates.TemplateResponse(
        "people.html",
        {
            "request": request,
            "people": people_data,
            "page": page,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
        },
    )


@app.post("/api/social/captures", dependencies=[Depends(require_social_api_key)])
def api_social_capture(payload: CaptureBatch, db: Session = Depends(get_db)):
    result = ingest_capture_batch(db, payload)
    return {"status": "ok", "platform": payload.platform, **result}


@app.get("/api/social/accounts/search")
def api_social_account_search(
    q: str = Query(..., min_length=1),
    platform: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(SocialAccount)
    if platform:
        try:
            normalized_platform = normalize_platform(platform)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        query = query.filter(SocialAccount.platform == normalized_platform)

    term = f"%{q.strip()}%"
    rows = (
        query.filter(
            or_(
                SocialAccount.handle.ilike(term),
                SocialAccount.display_name.ilike(term),
                SocialAccount.platform_account_id.ilike(term),
            )
        )
        .order_by(SocialAccount.platform.asc(), SocialAccount.id.asc())
        .limit(limit)
        .all()
    )
    return {
        "results": [
            {
                "id": row.id,
                "platform": row.platform,
                "platform_account_id": row.platform_account_id,
                "handle": row.handle,
                "display_name": row.display_name,
                "profile_url": row.profile_url,
            }
            for row in rows
        ]
    }


@app.get("/api/social/accounts/{account_id}/ego")
def api_social_ego(
    account_id: int,
    direction: str = Query(default="both"),
    interaction_type: Optional[str] = Query(default=None, alias="type"),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return query_ego_network(
            db,
            account_id=account_id,
            direction=direction,
            interaction_type=interaction_type,
            since=since,
            until=until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/social")
def social_page(
    request: Request,
    q: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    account_id: Optional[int] = Query(default=None),
    direction: str = Query(default="both"),
    interaction_type: Optional[str] = Query(default=None, alias="type"),
    db: Session = Depends(get_db),
):
    source_account = aliased(SocialAccount)
    target_account = aliased(SocialAccount)
    dashboard_rows = (
        db.query(
            SocialInteraction.id.label("id"),
            SocialInteraction.platform.label("platform"),
            SocialInteraction.interaction_type.label("interaction_type"),
            SocialInteraction.count.label("count"),
            SocialInteraction.last_seen_at.label("last_seen_at"),
            SocialInteraction.text_snippet.label("text_snippet"),
            source_account.id.label("source_id"),
            source_account.handle.label("source_handle"),
            source_account.display_name.label("source_display_name"),
            target_account.id.label("target_id"),
            target_account.handle.label("target_handle"),
            target_account.display_name.label("target_display_name"),
        )
        .join(source_account, SocialInteraction.source_account_id == source_account.id)
        .join(target_account, SocialInteraction.target_account_id == target_account.id)
        .order_by(SocialInteraction.last_seen_at.desc())
        .limit(30)
        .all()
    )
    dashboard_stats = {
        "accounts": db.query(func.count(SocialAccount.id)).scalar() or 0,
        "interactions": db.query(func.count(SocialInteraction.id)).scalar() or 0,
        "captures": db.query(func.count(SocialCaptureRaw.id)).scalar() or 0,
    }

    selected_platform = ""
    if platform:
        try:
            selected_platform = normalize_platform(platform)
        except ValueError:
            selected_platform = ""

    results: List[SocialAccount] = []
    if q:
        account_query = db.query(SocialAccount)
        if selected_platform:
            account_query = account_query.filter(SocialAccount.platform == selected_platform)
        term = f"%{q.strip()}%"
        results = (
            account_query.filter(
                or_(
                    SocialAccount.handle.ilike(term),
                    SocialAccount.display_name.ilike(term),
                    SocialAccount.platform_account_id.ilike(term),
                )
            )
            .order_by(SocialAccount.platform.asc(), SocialAccount.id.asc())
            .limit(50)
            .all()
        )

    ego_data = None
    if account_id:
        try:
            ego_data = query_ego_network(
                db,
                account_id=account_id,
                direction=direction,
                interaction_type=interaction_type,
            )
        except (LookupError, ValueError):
            ego_data = None

    return templates.TemplateResponse(
        "social.html",
        {
            "request": request,
            "search_query": q or "",
            "selected_platform": selected_platform,
            "platform_options": sorted(SUPPORTED_PLATFORMS),
            "results": results,
            "selected_account_id": account_id,
            "direction": direction,
            "interaction_type": interaction_type or "",
            "interaction_types": sorted(INTERACTION_TYPES),
            "ego": ego_data,
            "dashboard_rows": dashboard_rows,
            "dashboard_stats": dashboard_stats,
        },
    )


@app.get("/admin")
def admin(request: Request, db: Session = Depends(get_db)):
    people_count = db.query(func.count(Person.id)).scalar() or 0
    face_count = db.query(func.count(Face.id)).scalar() or 0
    social_account_count = db.query(func.count(SocialAccount.id)).scalar() or 0
    social_interaction_count = db.query(func.count(SocialInteraction.id)).scalar() or 0
    social_capture_count = db.query(func.count(SocialCaptureRaw.id)).scalar() or 0
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "people_count": people_count,
            "face_count": face_count,
            "social_account_count": social_account_count,
            "social_interaction_count": social_interaction_count,
            "social_capture_count": social_capture_count,
        },
    )


@app.post("/admin/clear-person-face")
def clear_person_face_data(db: Session = Depends(get_db)):
    db.query(Face).delete(synchronize_session=False)
    db.query(Person).delete(synchronize_session=False)
    db.query(Image).update({Image.contains_person: False}, synchronize_session=False)
    db.commit()
    matcher.reset()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/clear-social-data")
def clear_social_data(db: Session = Depends(get_db)):
    db.query(SocialInteraction).delete(synchronize_session=False)
    db.query(SocialContent).delete(synchronize_session=False)
    db.query(SocialAccount).delete(synchronize_session=False)
    db.query(SocialCaptureRaw).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/person/{person_id}")
def person_detail(person_id: int, request: Request, db: Session = Depends(get_db)):
    person = db.query(Person).filter(Person.id == person_id).first()
    if person is None:
        return RedirectResponse(url="/people", status_code=303)

    faces = db.query(Face).filter(Face.person_id == person_id).all()
    image_ids = sorted({f.image_id for f in faces})

    images = []
    if image_ids:
        images = db.query(Image).filter(Image.id.in_(image_ids)).order_by(Image.id.asc()).all()

    return templates.TemplateResponse(
        "person_detail.html",
        {
            "request": request,
            "person": person,
            "faces": faces,
            "images": images,
        },
    )
