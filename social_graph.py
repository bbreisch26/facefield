import hashlib
import json
import re
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased

from models import SocialAccount, SocialCaptureRaw, SocialContent, SocialInteraction

SUPPORTED_PLATFORMS = {"facebook", "instagram", "x"}
PLATFORM_ALIASES = {"twitter": "x"}
INTERACTION_TYPES = {"comment", "reply", "mention"}
MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_.]{2,30})")


def normalize_platform(platform: str) -> str:
    value = platform.strip().lower()
    value = PLATFORM_ALIASES.get(value, value)
    if value not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    return value


def extract_mentions(text: str) -> List[str]:
    if not text:
        return []
    handles = [m.group(1).lower() for m in MENTION_PATTERN.finditer(text)]
    return sorted(set(handles))


def canonical_interaction_key(
    *,
    platform: str,
    interaction_type: str,
    source_account_key: str,
    target_account_key: str,
    content_id: Optional[str],
    content_url: Optional[str],
    parent_content_id: Optional[str],
    evidence_ref: Optional[str],
) -> str:
    raw = "|".join(
        [
            normalize_platform(platform),
            interaction_type.strip().lower(),
            source_account_key.strip(),
            target_account_key.strip(),
            (content_id or "").strip(),
            (content_url or "").strip(),
            (parent_content_id or "").strip(),
            (evidence_ref or "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AccountPayload(BaseModel):
    platform_account_id: str = Field(..., min_length=1, max_length=1000)
    handle: Optional[str] = Field(default=None, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=400)
    profile_url: Optional[str] = Field(default=None, max_length=1000)


class InteractionPayload(BaseModel):
    interaction_type: Literal["comment", "reply", "mention"]
    source_account: AccountPayload
    target_account: AccountPayload
    content_id: Optional[str] = Field(default=None, max_length=1000)
    content_url: Optional[str] = Field(default=None, max_length=1000)
    parent_content_id: Optional[str] = Field(default=None, max_length=1000)
    text_snippet: Optional[str] = Field(default=None, max_length=5000)
    evidence_ref: Optional[str] = Field(default=None, max_length=1000)
    occurred_at: Optional[datetime] = None


class CaptureBatch(BaseModel):
    platform: str
    captured_at: datetime
    page_url: str = Field(..., min_length=1, max_length=1000)
    collector_version: str = Field(..., min_length=1, max_length=100)
    interactions: List[InteractionPayload]

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        return normalize_platform(value)


def upsert_account(db: Session, platform: str, payload: AccountPayload) -> SocialAccount:
    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.platform == platform,
            SocialAccount.platform_account_id == payload.platform_account_id,
        )
        .first()
    )
    if account is None:
        account = SocialAccount(
            platform=platform,
            platform_account_id=payload.platform_account_id,
        )
        db.add(account)
        db.flush()

    account.handle = payload.handle or account.handle
    account.display_name = payload.display_name or account.display_name
    account.profile_url = payload.profile_url or account.profile_url
    return account


def upsert_content(
    db: Session,
    *,
    platform: str,
    content_id: Optional[str],
    content_url: Optional[str],
    parent_content_id: Optional[str],
) -> Optional[SocialContent]:
    if not content_id and not content_url:
        return None

    query = db.query(SocialContent).filter(SocialContent.platform == platform)
    if content_id:
        content = query.filter(SocialContent.external_content_id == content_id).first()
    else:
        content = query.filter(SocialContent.content_url == content_url).first()

    if content is None:
        content = SocialContent(
            platform=platform,
            external_content_id=content_id,
            content_url=content_url,
            parent_external_content_id=parent_content_id,
        )
        db.add(content)
        db.flush()
        return content

    content.external_content_id = content_id or content.external_content_id
    content.content_url = content_url or content.content_url
    content.parent_external_content_id = parent_content_id or content.parent_external_content_id
    return content


def store_capture_raw(db: Session, payload: CaptureBatch) -> SocialCaptureRaw:
    raw = SocialCaptureRaw(
        platform=payload.platform,
        captured_at=payload.captured_at,
        page_url=payload.page_url,
        collector_version=payload.collector_version,
        payload_json=json.dumps(payload.model_dump(), default=str),
    )
    db.add(raw)
    db.flush()
    return raw


def ingest_capture_batch(db: Session, payload: CaptureBatch) -> Dict[str, int]:
    capture_raw = store_capture_raw(db, payload)
    inserted = 0
    updated = 0
    pending_rows_by_key: Dict[str, SocialInteraction] = {}

    for interaction in payload.interactions:
        source = upsert_account(db, payload.platform, interaction.source_account)
        target = upsert_account(db, payload.platform, interaction.target_account)
        content = upsert_content(
            db,
            platform=payload.platform,
            content_id=interaction.content_id,
            content_url=interaction.content_url,
            parent_content_id=interaction.parent_content_id,
        )
        key = canonical_interaction_key(
            platform=payload.platform,
            interaction_type=interaction.interaction_type,
            source_account_key=interaction.source_account.platform_account_id,
            target_account_key=interaction.target_account.platform_account_id,
            content_id=interaction.content_id,
            content_url=interaction.content_url,
            parent_content_id=interaction.parent_content_id,
            evidence_ref=interaction.evidence_ref,
        )

        row = pending_rows_by_key.get(key)
        if row is None:
            row = db.query(SocialInteraction).filter(SocialInteraction.canonical_key == key).first()
        if row is None:
            row = SocialInteraction(
                platform=payload.platform,
                capture_raw_id=capture_raw.id,
                canonical_key=key,
                interaction_type=interaction.interaction_type,
                source_account_id=source.id,
                target_account_id=target.id,
                content_id=content.id if content else None,
                evidence_ref=interaction.evidence_ref,
                text_snippet=interaction.text_snippet,
                first_seen_at=payload.captured_at,
                last_seen_at=payload.captured_at,
                last_occurred_at=interaction.occurred_at,
                count=1,
            )
            db.add(row)
            pending_rows_by_key[key] = row
            inserted += 1
        else:
            row.last_seen_at = payload.captured_at
            row.last_occurred_at = interaction.occurred_at or row.last_occurred_at
            row.text_snippet = interaction.text_snippet or row.text_snippet
            row.capture_raw_id = capture_raw.id
            row.count += 1
            updated += 1

    db.commit()
    return {"inserted": inserted, "updated": updated}


def validate_api_key(*, provided_key: Optional[str], expected_key: str) -> None:
    if not expected_key:
        raise ValueError("Server is missing required SOCIAL_API_KEY configuration.")
    if not provided_key or provided_key != expected_key:
        raise PermissionError("Invalid or missing X-API-Key.")


def query_ego_network(
    db: Session,
    *,
    account_id: int,
    direction: str = "both",
    interaction_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> Dict:
    if direction not in {"in", "out", "both"}:
        raise ValueError("direction must be one of: in, out, both.")
    if interaction_type and interaction_type not in INTERACTION_TYPES:
        raise ValueError("Invalid interaction type.")

    account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
    if account is None:
        raise LookupError("Account not found.")

    source_account = aliased(SocialAccount)
    target_account = aliased(SocialAccount)
    query = (
        db.query(
            SocialInteraction,
            source_account.handle.label("source_handle"),
            source_account.display_name.label("source_display_name"),
            target_account.handle.label("target_handle"),
            target_account.display_name.label("target_display_name"),
        )
        .join(source_account, SocialInteraction.source_account_id == source_account.id)
        .join(target_account, SocialInteraction.target_account_id == target_account.id)
    )
    if direction == "in":
        query = query.filter(SocialInteraction.target_account_id == account_id)
    elif direction == "out":
        query = query.filter(SocialInteraction.source_account_id == account_id)
    else:
        query = query.filter(
            or_(
                SocialInteraction.source_account_id == account_id,
                SocialInteraction.target_account_id == account_id,
            )
        )

    if interaction_type:
        query = query.filter(SocialInteraction.interaction_type == interaction_type)
    if since:
        query = query.filter(SocialInteraction.last_seen_at >= since)
    if until:
        query = query.filter(SocialInteraction.last_seen_at <= until)

    rows = query.order_by(SocialInteraction.last_seen_at.desc()).all()
    aggregated: Dict[tuple, Dict] = {}

    for row, source_handle, source_display_name, target_handle, target_display_name in rows:
        if row.source_account_id == account_id and row.target_account_id == account_id:
            edge_direction = "both"
            counterpart_id = account_id
            counterpart_handle = source_handle
            counterpart_display_name = source_display_name
        elif row.source_account_id == account_id:
            edge_direction = "out"
            counterpart_id = row.target_account_id
            counterpart_handle = target_handle
            counterpart_display_name = target_display_name
        else:
            edge_direction = "in"
            counterpart_id = row.source_account_id
            counterpart_handle = source_handle
            counterpart_display_name = source_display_name

        key = (counterpart_id, edge_direction, row.interaction_type)
        bucket = aggregated.get(key)
        if bucket is None:
            bucket = {
                "counterpart_account_id": counterpart_id,
                "counterpart_handle": counterpart_handle,
                "counterpart_display_name": counterpart_display_name,
                "direction": edge_direction,
                "interaction_type": row.interaction_type,
                "total_count": 0,
                "last_seen_at": row.last_seen_at,
                "latest_text_snippet": row.text_snippet,
            }
            aggregated[key] = bucket

        bucket["total_count"] += row.count
        if row.last_seen_at > bucket["last_seen_at"]:
            bucket["last_seen_at"] = row.last_seen_at
            bucket["latest_text_snippet"] = row.text_snippet

    edges = sorted(
        aggregated.values(),
        key=lambda item: (item["direction"], -item["total_count"], item["counterpart_account_id"]),
    )
    return {
        "account": {
            "id": account.id,
            "platform": account.platform,
            "platform_account_id": account.platform_account_id,
            "handle": account.handle,
            "display_name": account.display_name,
            "profile_url": account.profile_url,
        },
        "direction": direction,
        "interaction_type": interaction_type,
        "since": since,
        "until": until,
        "edges": edges,
    }
