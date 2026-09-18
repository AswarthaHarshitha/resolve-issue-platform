from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import require_admin
from app.db.session import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.admin import (
    CategoryAdminPublic,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    RoutingRuleAdminPublic,
    RoutingRuleCreateRequest,
    RoutingRuleUpdateRequest,
    SLARuleAdminPublic,
    SLARuleCreateRequest,
    SLARuleUpdateRequest,
    SubCategoryCreateRequest,
    SubCategoryUpdateRequest,
    TeamAdminPublic,
    TeamCreateRequest,
    TeamUpdateRequest,
    UserAdminUpdateRequest,
)
from app.schemas.user import UserPublic
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _handle_integrity_error(exc: IntegrityError):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This conflicts with existing configuration")


# --- Teams -----------------------------------------------------------------


@router.get("/teams", response_model=list[TeamAdminPublic])
def list_teams(db: Session = Depends(get_db)) -> list[TeamAdminPublic]:
    return admin_service.list_teams(db)


@router.post("/teams", response_model=TeamAdminPublic, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreateRequest, db: Session = Depends(get_db)) -> TeamAdminPublic:
    try:
        return admin_service.create_team(db, name=payload.name, description=payload.description)
    except IntegrityError as exc:
        _handle_integrity_error(exc)


@router.patch("/teams/{team_id}", response_model=TeamAdminPublic)
def update_team(team_id: UUID, payload: TeamUpdateRequest, db: Session = Depends(get_db)) -> TeamAdminPublic:
    try:
        return admin_service.update_team(
            db, team_id=team_id, name=payload.name, description=payload.description, is_active=payload.is_active
        )
    except admin_service.NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    except IntegrityError as exc:
        _handle_integrity_error(exc)


# --- Categories --------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryAdminPublic])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryAdminPublic]:
    return admin_service.list_categories(db)


@router.post("/categories", response_model=CategoryAdminPublic, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreateRequest, db: Session = Depends(get_db)) -> CategoryAdminPublic:
    try:
        return admin_service.create_category(db, name=payload.name, description=payload.description)
    except IntegrityError as exc:
        _handle_integrity_error(exc)


@router.patch("/categories/{category_id}", response_model=CategoryAdminPublic)
def update_category(
    category_id: UUID, payload: CategoryUpdateRequest, db: Session = Depends(get_db)
) -> CategoryAdminPublic:
    try:
        return admin_service.update_category(
            db,
            category_id=category_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
        )
    except admin_service.NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    except IntegrityError as exc:
        _handle_integrity_error(exc)


@router.post(
    "/categories/{category_id}/sub-categories",
    response_model=CategoryAdminPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_sub_category(
    category_id: UUID, payload: SubCategoryCreateRequest, db: Session = Depends(get_db)
) -> CategoryAdminPublic:
    try:
        admin_service.create_sub_category(db, category_id=category_id, name=payload.name)
        return db.get(Category, category_id)
    except admin_service.NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    except IntegrityError as exc:
        _handle_integrity_error(exc)


@router.patch("/sub-categories/{sub_category_id}", response_model=CategoryAdminPublic)
def update_sub_category(
    sub_category_id: UUID, payload: SubCategoryUpdateRequest, db: Session = Depends(get_db)
) -> CategoryAdminPublic:
    try:
        sub_category = admin_service.update_sub_category(
            db, sub_category_id=sub_category_id, name=payload.name, is_active=payload.is_active
        )
        return db.get(Category, sub_category.category_id)
    except admin_service.NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-category not found")
    except IntegrityError as exc:
        _handle_integrity_error(exc)


# --- Routing rules -----------------------------------------------------------


@router.get("/routing-rules", response_model=list[RoutingRuleAdminPublic])
def list_routing_rules(db: Session = Depends(get_db)) -> list[RoutingRuleAdminPublic]:
    return admin_service.list_routing_rules(db)


@router.post("/routing-rules", response_model=RoutingRuleAdminPublic, status_code=status.HTTP_201_CREATED)
def create_routing_rule(payload: RoutingRuleCreateRequest, db: Session = Depends(get_db)) -> RoutingRuleAdminPublic:
    try:
        return admin_service.create_routing_rule(
            db, category_id=payload.category_id, sub_category_id=payload.sub_category_id, team_id=payload.team_id
        )
    except admin_service.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    except admin_service.ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IntegrityError as exc:
        _handle_integrity_error(exc)


@router.patch("/routing-rules/{rule_id}", response_model=RoutingRuleAdminPublic)
def update_routing_rule(
    rule_id: UUID, payload: RoutingRuleUpdateRequest, db: Session = Depends(get_db)
) -> RoutingRuleAdminPublic:
    try:
        return admin_service.update_routing_rule(
            db, rule_id=rule_id, team_id=payload.team_id, is_active=payload.is_active
        )
    except admin_service.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    except IntegrityError as exc:
        _handle_integrity_error(exc)


# --- SLA rules ------------------------------------------------------------


@router.get("/sla-rules", response_model=list[SLARuleAdminPublic])
def list_sla_rules(db: Session = Depends(get_db)) -> list[SLARuleAdminPublic]:
    return admin_service.list_sla_rules(db)


@router.post("/sla-rules", response_model=SLARuleAdminPublic, status_code=status.HTTP_201_CREATED)
def create_sla_rule(payload: SLARuleCreateRequest, db: Session = Depends(get_db)) -> SLARuleAdminPublic:
    try:
        return admin_service.create_sla_rule(
            db,
            category_id=payload.category_id,
            priority=payload.priority,
            first_response_minutes=payload.first_response_minutes,
            resolution_minutes=payload.resolution_minutes,
        )
    except admin_service.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    except admin_service.ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IntegrityError as exc:
        _handle_integrity_error(exc)


@router.patch("/sla-rules/{rule_id}", response_model=SLARuleAdminPublic)
def update_sla_rule(
    rule_id: UUID, payload: SLARuleUpdateRequest, db: Session = Depends(get_db)
) -> SLARuleAdminPublic:
    try:
        return admin_service.update_sla_rule(
            db,
            rule_id=rule_id,
            first_response_minutes=payload.first_response_minutes,
            resolution_minutes=payload.resolution_minutes,
            is_active=payload.is_active,
        )
    except admin_service.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    except admin_service.ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IntegrityError as exc:
        _handle_integrity_error(exc)


# --- Users -----------------------------------------------------------------


@router.get("/users", response_model=list[UserPublic])
def list_users(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
) -> list[UserPublic]:
    return admin_service.list_users(db, page=page, page_size=page_size)


@router.patch("/users/{user_id}", response_model=UserPublic)
def update_user(user_id: UUID, payload: UserAdminUpdateRequest, db: Session = Depends(get_db)) -> UserPublic:
    try:
        return admin_service.update_user(
            db, user_id=user_id, role=payload.role, team_id=payload.team_id, is_active=payload.is_active
        )
    except admin_service.NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except admin_service.ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
