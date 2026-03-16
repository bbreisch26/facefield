from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import SocialAccount, SocialInteraction
from social_graph import (
    CaptureBatch,
    canonical_interaction_key,
    extract_mentions,
    ingest_capture_batch,
    query_ego_network,
    validate_api_key,
)


def make_session(tmp_path):
    db_path = tmp_path / "social_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def sample_payload(captured_at: datetime):
    return CaptureBatch.model_validate(
        {
            "platform": "facebook",
            "captured_at": captured_at.isoformat(),
            "page_url": "https://facebook.com/example/posts/1",
            "collector_version": "test-v1",
            "interactions": [
                {
                    "interaction_type": "comment",
                    "source_account": {
                        "platform_account_id": "alice",
                        "handle": "alice",
                        "display_name": "Alice"
                    },
                    "target_account": {
                        "platform_account_id": "page_owner",
                        "handle": "page_owner",
                        "display_name": "Page Owner"
                    },
                    "content_id": "comment-1",
                    "content_url": "https://facebook.com/example/posts/1?comment_id=1",
                    "text_snippet": "hello @bob",
                    "evidence_ref": "https://facebook.com/example/posts/1?comment_id=1",
                    "occurred_at": captured_at.isoformat(),
                }
            ],
        }
    )


def test_extract_mentions_and_key_stability():
    text = "Hey @Alice and @bob, ping @Alice again"
    assert extract_mentions(text) == ["alice", "bob"]

    key_one = canonical_interaction_key(
        platform="facebook",
        interaction_type="comment",
        source_account_key="alice",
        target_account_key="page_owner",
        content_id="c1",
        content_url="https://facebook.com/post/1",
        parent_content_id="",
        evidence_ref="https://facebook.com/post/1#c1",
    )
    key_two = canonical_interaction_key(
        platform="facebook",
        interaction_type="comment",
        source_account_key="alice",
        target_account_key="page_owner",
        content_id="c1",
        content_url="https://facebook.com/post/1",
        parent_content_id="",
        evidence_ref="https://facebook.com/post/1#c1",
    )
    assert key_one == key_two


def test_ingest_capture_dedupes_by_canonical_key(tmp_path):
    db = make_session(tmp_path)
    t0 = datetime(2026, 3, 1, 12, 0, 0)
    t1 = t0 + timedelta(minutes=10)

    first = ingest_capture_batch(db, sample_payload(t0))
    second = ingest_capture_batch(db, sample_payload(t1))

    assert first == {"inserted": 1, "updated": 0}
    assert second == {"inserted": 0, "updated": 1}

    rows = db.query(SocialInteraction).all()
    assert len(rows) == 1
    assert rows[0].count == 2
    assert rows[0].first_seen_at == t0
    assert rows[0].last_seen_at == t1


def test_query_ego_network_direction_and_type_filters(tmp_path):
    db = make_session(tmp_path)
    t0 = datetime(2026, 3, 1, 9, 0, 0)

    payload = CaptureBatch.model_validate(
        {
            "platform": "facebook",
            "captured_at": t0.isoformat(),
            "page_url": "https://facebook.com/example/posts/2",
            "collector_version": "test-v1",
            "interactions": [
                {
                    "interaction_type": "comment",
                    "source_account": {"platform_account_id": "alice", "handle": "alice"},
                    "target_account": {"platform_account_id": "bob", "handle": "bob"},
                    "content_id": "comment-100",
                    "content_url": "https://facebook.com/post/2?comment=100",
                },
                {
                    "interaction_type": "mention",
                    "source_account": {"platform_account_id": "carol", "handle": "carol"},
                    "target_account": {"platform_account_id": "alice", "handle": "alice"},
                    "content_id": "comment-101",
                    "content_url": "https://facebook.com/post/2?comment=101",
                },
                {
                    "interaction_type": "reply",
                    "source_account": {"platform_account_id": "alice", "handle": "alice"},
                    "target_account": {"platform_account_id": "dave", "handle": "dave"},
                    "content_id": "comment-102",
                    "content_url": "https://facebook.com/post/2?comment=102",
                },
            ],
        }
    )

    ingest_capture_batch(db, payload)
    alice = (
        db.query(SocialAccount)
        .filter(SocialAccount.platform == "facebook", SocialAccount.platform_account_id == "alice")
        .first()
    )
    assert alice is not None

    both = query_ego_network(db, account_id=alice.id, direction="both")
    assert len(both["edges"]) == 3
    directions = {edge["direction"] for edge in both["edges"]}
    assert directions == {"in", "out"}

    mention_only = query_ego_network(
        db,
        account_id=alice.id,
        direction="both",
        interaction_type="mention",
    )
    assert len(mention_only["edges"]) == 1
    assert mention_only["edges"][0]["direction"] == "in"


def test_ingest_duplicate_keys_within_same_payload(tmp_path):
    db = make_session(tmp_path)
    t0 = datetime(2026, 3, 1, 15, 0, 0)
    single = sample_payload(t0).model_dump()
    single["interactions"] = single["interactions"] * 2
    payload = CaptureBatch.model_validate(single)

    result = ingest_capture_batch(db, payload)
    assert result == {"inserted": 1, "updated": 1}

    rows = db.query(SocialInteraction).all()
    assert len(rows) == 1
    assert rows[0].count == 2


def test_validate_api_key_enforcement():
    validate_api_key(provided_key="abc123", expected_key="abc123")

    try:
        validate_api_key(provided_key="wrong", expected_key="abc123")
        assert False, "Expected PermissionError"
    except PermissionError:
        pass

    try:
        validate_api_key(provided_key="abc123", expected_key="")
        assert False, "Expected ValueError"
    except ValueError:
        pass
