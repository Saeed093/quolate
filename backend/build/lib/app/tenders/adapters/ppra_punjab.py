"""PPRA Punjab (ppra.punjab.gov.pk) adapter."""
from __future__ import annotations

from app.tenders.adapters.base import BaseAdapter


class PpraPunjabAdapter(BaseAdapter):
    name = "ppra_punjab"
    default_org_type = "provincial"
