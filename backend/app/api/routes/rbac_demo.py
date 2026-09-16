"""Temporary endpoints that exist only to exercise the RBAC dependency chain
(app/core/deps.py + app/core/roles.py) over real HTTP requests. Phase 3 has
no real protected business endpoints yet - issues, teams, and everything
else land in later phases - so there is nothing else to test role
enforcement against. Remove this router once Phase 4+ introduces real
protected endpoints to test instead."""

from fastapi import APIRouter, Depends

from app.core.roles import require_admin, require_resolver, require_resolver_or_admin, require_user
from app.models.user import User

router = APIRouter(prefix="/_rbac-demo", tags=["rbac-demo"])


@router.get("/user-only")
def user_only(current_user: User = Depends(require_user)) -> dict:
    return {"ok": True, "role": current_user.role.name}


@router.get("/resolver-only")
def resolver_only(current_user: User = Depends(require_resolver)) -> dict:
    return {"ok": True, "role": current_user.role.name}


@router.get("/admin-only")
def admin_only(current_user: User = Depends(require_admin)) -> dict:
    return {"ok": True, "role": current_user.role.name}


@router.get("/resolver-or-admin")
def resolver_or_admin(current_user: User = Depends(require_resolver_or_admin)) -> dict:
    return {"ok": True, "role": current_user.role.name}
