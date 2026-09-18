"""Development-only bootstrap: creates exactly one local ADMIN account so a
developer can reach admin-only UI/API without hand-writing SQL.

This is NOT a production provisioning mechanism and is NOT how a real
deployment gets its first admin - that remains a deliberate, one-time direct
database action performed by whoever operates the deployment (DECISIONS.md
D23 - registration can never create a RESOLVER/ADMIN, by design). This
script exists only because that same one-time step was, until now, done by
hand with raw SQL during every phase's local verification. It follows the
exact isolation pattern already established by seed_dev_reference_data.py:

  - it refuses to run unless ENVIRONMENT=development
  - it is never imported or called by application code (no migration, no
    startup hook, no HTTP route anywhere references it)
  - it is not, and must never become, an API endpoint - it only runs as a
    one-off local script a developer invokes themselves
  - it uses the real password hashing path (app.core.security.hash_password)
    - never a plaintext or weakened hash
  - it is idempotent and safe to re-run: if an account with the target email
    already exists, its role is left untouched and its email is reported,
    never silently re-promoted or reset

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.bootstrap_dev_admin [--email EMAIL] [--full-name NAME]

Reads DEV_ADMIN_EMAIL / DEV_ADMIN_PASSWORD from the environment if set;
otherwise defaults the email to admin@example.com and generates a random
password. The password is never written to a file and is printed to stdout
exactly once, clearly labeled as a local-development-only credential.
"""

import argparse
import secrets
import sys

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.core.roles import RoleName
from app.repositories import role_repository, user_repository


def bootstrap(email: str, password: str, full_name: str) -> None:
    settings = get_settings()
    if settings.environment != "development":
        print(
            f"Refusing to run: ENVIRONMENT={settings.environment!r}, not 'development'. "
            "This script is a local-dev convenience only and must never run against a "
            "production or staging database.",
            file=sys.stderr,
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = user_repository.get_user_by_email(db, email)
        if existing is not None:
            print(f"An account already exists for {email} (role={existing.role.name}). Role left unchanged.")
            return

        admin_role = role_repository.get_role_by_name(db, RoleName.ADMIN)
        if admin_role is None:
            # Would mean the seed migration (DECISIONS.md D16) never ran.
            raise RuntimeError("ADMIN role is not seeded in the database - run migrations first")

        user_repository.create_user(
            db,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role_id=admin_role.id,
        )
        db.commit()

        print("Created a local development ADMIN account.")
        print("=" * 60)
        print("LOCAL DEVELOPMENT ONLY - do not reuse, commit, or deploy this credential")
        print(f"  email:    {email}")
        print(f"  password: {password}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    import os

    parser = argparse.ArgumentParser(description="Bootstrap a local development ADMIN account.")
    parser.add_argument("--email", default=os.environ.get("DEV_ADMIN_EMAIL", "admin@example.com"))
    parser.add_argument("--full-name", default="Dev Admin")
    args = parser.parse_args()

    generated_password = os.environ.get("DEV_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    bootstrap(args.email, generated_password, args.full_name)
