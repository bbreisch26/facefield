from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    from models import Base as ModelsBase

    ModelsBase.metadata.create_all(bind=engine)
    _ensure_images_columns()


def _ensure_images_columns() -> None:
    with engine.begin() as conn:
        columns = conn.execute(text("PRAGMA table_info(images)")).fetchall()
        column_names = {row[1] for row in columns}
        if "ingest_page_url" not in column_names:
            conn.execute(text("ALTER TABLE images ADD COLUMN ingest_page_url VARCHAR"))
