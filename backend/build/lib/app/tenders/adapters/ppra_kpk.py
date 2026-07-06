"""KPK PPRA (kppra.gov.pk) adapter."""
from __future__ import annotations

from app.tenders.adapters.base import BaseAdapter


class PpraKpkAdapter(BaseAdapter):
    name = "ppra_kpk"
    default_org_type = "provincial"
