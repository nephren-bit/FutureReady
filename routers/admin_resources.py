"""
routers/admin_resources.py

The learning-resource catalog — row 12 of the Project 1 report's permission
matrix, reachable only by AC-04 Quản trị viên.

Kept in its own module rather than added to `routers/admin.py` because the two
manage unrelated things: one governs who may use the system, the other governs
what the Recommendation Engine is allowed to suggest. They share only the
`/admin` prefix and the `require_admin` dependency.

Hide, never delete
------------------
There is no DELETE endpoint. `RecommendationORM` rows carry a foreign key to
`learning_resources`, so a resource is part of the record of what a learner
was once told to study. Deleting one would either cascade that history away or
leave rows pointing at nothing; hiding it via `is_active` stops the engine
suggesting it again while leaving what already happened intact. The report's
own wording for this row is "thêm, sửa, **ẩn** tài nguyên" — add, edit, hide.

Every response carries `recommendation_count` so the person deciding whether
to hide something can see how much history hangs off it first.
"""

from __future__ import annotations

import uuid
from collections import Counter

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from db.models import LearningResourceORM, RecommendationORM
from models.resource_models import (
    ResourceCreateRequest,
    ResourceListResponse,
    ResourcePublic,
    ResourceStatsResponse,
    ResourceType,
    ResourceUpdateRequest,
    SkillTag,
)
from routers.dependencies import CurrentAdmin, DbDep
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/resources", tags=["Administration"])


def _recommendation_counts(db: DbDep, resource_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """
    How many recommendations point at each of these resources.

    One grouped query for the whole page rather than a count per row, so
    listing 50 resources costs two queries instead of fifty-one.
    """
    if not resource_ids:
        return {}
    rows = db.execute(
        select(RecommendationORM.resource_id, func.count(RecommendationORM.id))
        .where(RecommendationORM.resource_id.in_(resource_ids))
        .group_by(RecommendationORM.resource_id)
    ).all()
    return {resource_id: count for resource_id, count in rows}


def _to_public(resource: LearningResourceORM, counts: dict[uuid.UUID, int]) -> ResourcePublic:
    """Serialize one resource, attaching its recommendation count."""
    public = ResourcePublic.model_validate(resource)
    public.recommendation_count = counts.get(resource.id, 0)
    return public


def _get_or_404(db: DbDep, resource_id: uuid.UUID) -> LearningResourceORM:
    """Fetch a resource or raise 404."""
    resource = db.get(LearningResourceORM, resource_id)
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài nguyên này."
        )
    return resource


@router.get("", response_model=ResourceListResponse, summary="Danh sách và tìm kiếm tài nguyên.")
def list_resources(
    admin: CurrentAdmin,
    db: DbDep,
    search: str | None = Query(None, description="Tìm trong tiêu đề, diễn giả, nguồn."),
    resource_type: ResourceType | None = Query(None),
    skill_tag: SkillTag | None = Query(None, description="Chỉ lấy tài nguyên mang nhãn này."),
    language: str | None = Query(None, pattern="^(vi|en)$"),
    is_active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ResourceListResponse:
    """One page of the catalog, with the filters the admin screen offers."""
    filters = []
    if search:
        pattern = f"%{search.strip().lower()}%"
        filters.append(
            or_(
                func.lower(LearningResourceORM.title).like(pattern),
                func.lower(func.coalesce(LearningResourceORM.speaker, "")).like(pattern),
                func.lower(func.coalesce(LearningResourceORM.source, "")).like(pattern),
            )
        )
    if resource_type is not None:
        filters.append(LearningResourceORM.resource_type == resource_type.value)
    if language is not None:
        filters.append(LearningResourceORM.language == language)
    if is_active is not None:
        filters.append(LearningResourceORM.is_active.is_(is_active))

    rows = db.scalars(
        select(LearningResourceORM).where(*filters).order_by(LearningResourceORM.created_at.desc())
    ).all()

    # `skill_tags` is a JSON column, and the containment operators differ
    # between PostgreSQL and SQLite. Filtering in Python keeps this working on
    # both; the catalog is a curated list in the tens or low hundreds, so the
    # cost of doing it here is not worth a dialect-specific query.
    if skill_tag is not None:
        rows = [r for r in rows if skill_tag.value in (r.skill_tags or [])]

    total = len(rows)
    page = rows[offset : offset + limit]
    counts = _recommendation_counts(db, [r.id for r in page])

    return ResourceListResponse(total=total, items=[_to_public(r, counts) for r in page])


@router.get("/stats", response_model=ResourceStatsResponse, summary="Số liệu tổng quan danh mục.")
def resource_stats(admin: CurrentAdmin, db: DbDep) -> ResourceStatsResponse:
    """Counts for the catalog screen, including resources no tag can reach."""
    resources = db.scalars(select(LearningResourceORM)).all()

    by_type: Counter[str] = Counter(r.resource_type for r in resources)
    by_tag: Counter[str] = Counter()
    untagged = 0
    for resource in resources:
        tags = resource.skill_tags or []
        if not tags:
            untagged += 1
        by_tag.update(tags)

    return ResourceStatsResponse(
        total=len(resources),
        active=sum(1 for r in resources if r.is_active),
        hidden=sum(1 for r in resources if not r.is_active),
        by_type=dict(by_type),
        by_skill_tag=dict(by_tag),
        untagged=untagged,
    )


@router.get("/{resource_id}", response_model=ResourcePublic, summary="Chi tiết một tài nguyên.")
def get_resource(resource_id: uuid.UUID, admin: CurrentAdmin, db: DbDep) -> ResourcePublic:
    """One catalog entry."""
    resource = _get_or_404(db, resource_id)
    return _to_public(resource, _recommendation_counts(db, [resource.id]))


@router.post(
    "",
    response_model=ResourcePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm tài nguyên vào danh mục.",
)
def create_resource(
    payload: ResourceCreateRequest, admin: CurrentAdmin, db: DbDep
) -> ResourcePublic:
    """
    Add a catalog entry.

    The URL is unique in the database, so the same talk cannot be catalogued
    twice under two titles and then recommended twice to the same learner.
    """
    existing = db.scalar(select(LearningResourceORM).where(LearningResourceORM.url == payload.url))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Đường dẫn này đã có trong danh mục: “{existing.title}”.",
        )

    resource = LearningResourceORM(
        title=payload.title,
        url=payload.url,
        resource_type=payload.resource_type.value,
        platform=payload.platform,
        language=payload.language,
        speaker=payload.speaker,
        source=payload.source,
        description=payload.description,
        skill_tags=[tag.value for tag in payload.skill_tags],
        category_label=payload.category_label,
        is_active=payload.is_active,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    if not resource.skill_tags:
        # Not an error -- a tag can be added later -- but worth a line in the
        # log, because until one is added the engine can never surface this.
        logger.warning(
            "Admin %s added resource %s with no skill tag; it cannot be recommended yet.",
            admin.id,
            resource.id,
        )
    logger.info("Admin %s added learning resource %s (%s).", admin.id, resource.id, resource.title)
    return _to_public(resource, {})


@router.patch("/{resource_id}", response_model=ResourcePublic, summary="Sửa hoặc ẩn tài nguyên.")
def update_resource(
    resource_id: uuid.UUID, payload: ResourceUpdateRequest, admin: CurrentAdmin, db: DbDep
) -> ResourcePublic:
    """
    Apply changes to one entry.

    Setting `is_active` to false is how a resource is retired: it stops being
    recommended, and every past recommendation of it stays readable.
    """
    resource = _get_or_404(db, resource_id)

    if payload.url is not None and payload.url != resource.url:
        clash = db.scalar(
            select(LearningResourceORM).where(
                LearningResourceORM.url == payload.url, LearningResourceORM.id != resource_id
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Đường dẫn này đã thuộc về tài nguyên khác: “{clash.title}”.",
            )

    changes: list[str] = []
    for field in ("title", "url", "platform", "language", "speaker", "source", "description", "category_label"):
        value = getattr(payload, field)
        if value is not None and value != getattr(resource, field):
            setattr(resource, field, value)
            changes.append(field)

    if payload.resource_type is not None and payload.resource_type.value != resource.resource_type:
        resource.resource_type = payload.resource_type.value
        changes.append("resource_type")

    if payload.skill_tags is not None:
        tags = [tag.value for tag in payload.skill_tags]
        if tags != (resource.skill_tags or []):
            resource.skill_tags = tags
            changes.append("skill_tags")

    if payload.is_active is not None and payload.is_active != resource.is_active:
        resource.is_active = payload.is_active
        changes.append(f"is_active -> {payload.is_active}")

    if changes:
        db.commit()
        db.refresh(resource)
        logger.info(
            "Admin %s updated resource %s: %s", admin.id, resource.id, ", ".join(changes)
        )

    return _to_public(resource, _recommendation_counts(db, [resource.id]))
