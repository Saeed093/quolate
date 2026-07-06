"""Seed a demo user + demo project with a small BOM.

Run: python -m app.scripts.seed   (or: .\tasks.ps1 seed)
Idempotent: skips creation if the demo user already exists.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.auth.security import hash_password
from app.db.models import BomItem, Project, Supplier, User
from app.db.session import SessionLocal

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DEMO_EMAIL = "demo@quolate.local"
DEMO_PASSWORD = "demo12345"


async def _seed() -> None:
    async with SessionLocal() as session:
        existing = await session.execute(
            select(User).where(User.email == DEMO_EMAIL)
        )
        if existing.scalar_one_or_none() is not None:
            print(f"Demo user already exists: {DEMO_EMAIL}")
            return

        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name="Demo Buyer",
        )
        session.add(user)
        await session.flush()

        project = Project(
            owner_id=user.id,
            name="Demo Sourcing Project",
            base_currency="USD",
            landed_cost_defaults={
                "duty_pct": 0.05,
                "freight_per_unit": 2.0,
                "lc_pct": 0.01,
                "fx_overrides": {},
            },
        )
        session.add(project)
        await session.flush()

        session.add_all(
            [
                BomItem(
                    project_id=project.id,
                    line_no=1,
                    part_name="Thermal Camera",
                    spec_requirement="640x480, 25mm lens",
                    quantity=100,
                    target_price=1200,
                ),
                BomItem(
                    project_id=project.id,
                    line_no=2,
                    part_name="Tripod",
                    spec_requirement="Aluminium, 1.5m",
                    quantity=100,
                    target_price=40,
                ),
            ]
        )
        session.add(
            Supplier(
                project_id=project.id,
                name="Shenzhen Widget Co.",
                country="China",
                default_currency="USD",
            )
        )
        await session.commit()
        print(f"Seeded demo user {DEMO_EMAIL} / {DEMO_PASSWORD} and a demo project.")


if __name__ == "__main__":
    asyncio.run(_seed())
