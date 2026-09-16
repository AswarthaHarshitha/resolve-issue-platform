from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Session:
    """FastAPI dependency. Each request/background task gets its own session
    (never reused across a request/task boundary — see DECISIONS.md D4)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
