from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String
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
