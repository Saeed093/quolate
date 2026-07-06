"""Matrix router: computed comparison matrix + XLSX export."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.db.models import User
from app.db.session import get_session
from app.matrix.builder import build_matrix
from app.matrix.export import matrix_to_xlsx

router = APIRouter(tags=["matrix"])


def _overrides(
    duty_pct: float | None,
    freight_per_unit: float | None,
    lc_pct: float | None,
) -> dict:
    return {
        "duty_pct": duty_pct,
        "freight_per_unit": freight_per_unit,
        "lc_pct": lc_pct,
    }


@router.get("/projects/{project_id}/matrix")
async def get_matrix(
    project_id: uuid.UUID,
    currency: str | None = None,
    duty_pct: float | None = None,
    freight_per_unit: float | None = None,
    lc_pct: float | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    project = await get_owned_project(project_id, user, session)
    return await build_matrix(
        session,
        project,
        currency=currency,
        overrides=_overrides(duty_pct, freight_per_unit, lc_pct),
    )


@router.get("/projects/{project_id}/matrix/export")
async def export_matrix(
    project_id: uuid.UUID,
    currency: str | None = None,
    duty_pct: float | None = None,
    freight_per_unit: float | None = None,
    lc_pct: float | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    project = await get_owned_project(project_id, user, session)
    matrix = await build_matrix(
        session,
        project,
        currency=currency,
        overrides=_overrides(duty_pct, freight_per_unit, lc_pct),
    )
    data = matrix_to_xlsx(matrix)
    filename = f"matrix-{project_id}.xlsx"
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
