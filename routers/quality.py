"""
routers/quality.py

The detection-quality dashboard (Nhom B Task 14 / Nhom C Task 18):
read-only, admin-only, listed under plan.md's "Giao diện quản trị"
alongside the accounts screen. See services/quality_tracking.py for what
it actually measures and why `PeerNote` is the only allowed source.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from db.models import UserORM
from db.session import get_db
from models.quality_models import QualityReportResponse
from models.responses import ErrorResponse
from routers.deps import require_admin
from services.quality_tracking import DEFAULT_TOLERANCE_SEC, compute_quality_report

router = APIRouter(prefix="/admin", tags=["Quality"])

_ERROR_RESPONSES = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}}


@router.get(
    "/quality-report",
    response_model=QualityReportResponse,
    responses=_ERROR_RESPONSES,
    summary="Cumulative detection accuracy against peer reviews, by event type and profile.",
)
async def get_quality_report(
    tolerance_sec: float = DEFAULT_TOLERANCE_SEC,
    current_user: UserORM = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> QualityReportResponse:
    report = compute_quality_report(db, tolerance_sec=tolerance_sec)
    return QualityReportResponse.from_report(report)
