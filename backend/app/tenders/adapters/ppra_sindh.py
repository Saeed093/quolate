"""Sindh PPRA (spprasindh.gov.pk) adapter."""
from __future__ import annotations

from app.tenders.adapters.base import BaseAdapter


class PpraSindhAdapter(BaseAdapter):
    name = "ppra_sindh"
    default_org_type = "provincial"
