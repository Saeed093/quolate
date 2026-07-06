"""Tender source adapters registry."""
from __future__ import annotations

from app.tenders.adapters.base import BaseAdapter, NoticeData, NoticeRef
from app.tenders.adapters.generic import GenericAdapter
from app.tenders.adapters.ppra_federal import PpraFederalAdapter
from app.tenders.adapters.ppra_kpk import PpraKpkAdapter
from app.tenders.adapters.ppra_punjab import PpraPunjabAdapter
from app.tenders.adapters.ppra_sindh import PpraSindhAdapter

_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "ppra_federal": PpraFederalAdapter,
    "ppra_punjab": PpraPunjabAdapter,
    "ppra_sindh": PpraSindhAdapter,
    "ppra_kpk": PpraKpkAdapter,
    "generic": GenericAdapter,
}


def get_adapter(name: str, base_url: str) -> BaseAdapter:
    cls = _ADAPTERS.get(name, GenericAdapter)
    return cls(base_url)


def adapter_names() -> list[str]:
    return list(_ADAPTERS.keys())


__all__ = [
    "BaseAdapter",
    "NoticeData",
    "NoticeRef",
    "get_adapter",
    "adapter_names",
]
