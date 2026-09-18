"""Development-only: resets an EXISTING account's password to a known
temporary value, for local testing when the original password isn't known
to whoever is sitting at the keyboard right now (e.g. it was set through the
UI by someone else).

Follows the exact isolation pattern already established by
seed_dev_reference_data.py and bootstrap_dev_admin.py:

  - refuses to run unless ENVIRONMENT=development
  - never imported or called by application code (no migration, no startup
    hook, no HTTP route anywhere references it) - this is not, and must
    never become, a "forgot password" API endpoint
  - uses the real password hashing path (app.core.security.hash_password) -
    never a plaintext or weakened hash
  - changes ONLY the password: role, team, and is_active are left exactly
    as they are. This is a password reset, not an account editor - use the
    admin API (or bootstrap_dev_admin.py for a fresh ADMIN) for anything
    else.
  - never creates an account - if the target email doesn't exist, it exits
    with an error rather than silently provisioning one with an arbitrary
    role.

Usage:
    cd backend && source .venv/bin/activate
    python -m scripts.reset_dev_password --email someone@example.com [--password PASSWORD]

If --password (or the DEV_RESET_PASSWORD env var) isn't given, a random
password is generated and printed to stdout exactly once - never written to
a file.
"""

import argparse
import secrets
import sys

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.repositories import user_repository


def reset_password(email: str, password: str) -> None:
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
        user = user_repository.get_user_by_email(db, email)
        if user is None:
            print(f"No account exists for {email} - this script never creates one.", file=sys.stderr)
            sys.exit(1)

        user.password_hash = hash_password(password)
        db.commit()

        print(f"Password reset for {email} (role={user.role.name}).")
        print("=" * 60)
        print("LOCAL DEVELOPMENT ONLY - do not reuse, commit, or deploy this credential")
        print(f"  email:    {email}")
        print(f"  password: {password}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    import os

    parser = argparse.ArgumentParser(description="Reset an existing local development account's password.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    new_password = args.password or os.environ.get("DEV_RESET_PASSWORD") or secrets.token_urlsafe(12)
    reset_password(args.email, new_password)
