from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: UUID) -> Optional[User]:
    return db.get(User, user_id)


def create_user(db: Session, *, email: str, password_hash: str, full_name: str, role_id: UUID) -> User:
    user = User(email=email, password_hash=password_hash, full_name=full_name, role_id=role_id)
    db.add(user)
    db.flush()
    return user
