from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    faces = relationship("Face", back_populates="person", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    ingest_page_url = Column(String, nullable=True)
    source_url = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    contains_person = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    faces = relationship("Face", back_populates="image", cascade="all, delete-orphan")


class Face(Base):
    __tablename__ = "faces"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    face_path = Column(String, nullable=False)

    image = relationship("Image", back_populates="faces")
    person = relationship("Person", back_populates="faces")


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_account_id", name="uq_social_accounts_platform_account"),
    )

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False, index=True)
    platform_account_id = Column(String, nullable=False)
    handle = Column(String, nullable=True, index=True)
    display_name = Column(String, nullable=True)
    profile_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SocialContent(Base):
    __tablename__ = "social_content"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False, index=True)
    external_content_id = Column(String, nullable=True, index=True)
    content_url = Column(String, nullable=True)
    parent_external_content_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SocialCaptureRaw(Base):
    __tablename__ = "social_capture_raw"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False, index=True)
    captured_at = Column(DateTime, nullable=False, index=True)
    page_url = Column(String, nullable=False)
    collector_version = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SocialInteraction(Base):
    __tablename__ = "social_interactions"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False, index=True)
    capture_raw_id = Column(Integer, ForeignKey("social_capture_raw.id"), nullable=False)
    canonical_key = Column(String, nullable=False, unique=True, index=True)
    interaction_type = Column(String, nullable=False, index=True)
    source_account_id = Column(Integer, ForeignKey("social_accounts.id"), nullable=False, index=True)
    target_account_id = Column(Integer, ForeignKey("social_accounts.id"), nullable=False, index=True)
    content_id = Column(Integer, ForeignKey("social_content.id"), nullable=True, index=True)
    evidence_ref = Column(String, nullable=True)
    text_snippet = Column(Text, nullable=True)
    first_seen_at = Column(DateTime, nullable=False, index=True)
    last_seen_at = Column(DateTime, nullable=False, index=True)
    last_occurred_at = Column(DateTime, nullable=True, index=True)
    count = Column(Integer, nullable=False, default=1)
