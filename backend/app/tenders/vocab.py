"""Controlled vocabularies for tender classification (fixed lists)."""
from __future__ import annotations

ORG_TYPES = ["federal", "provincial", "military", "soe", "other"]

CATEGORIES = ["goods", "works", "services", "consultancy"]

SECTOR_TAGS = [
    "defense",
    "medical",
    "it",
    "construction",
    "energy",
    "telecom",
    "transport",
    "education",
    "agriculture",
    "water",
    "aviation",
    "railways",
    "oil_gas",
    "power",
    "security",
    "surveillance",
    "laboratory",
    "pharmaceuticals",
    "vehicles",
    "furniture",
    "printing",
    "food",
    "textiles",
    "machinery",
    "electrical",
]

_SECTOR_SET = set(SECTOR_TAGS)
_ORG_SET = set(ORG_TYPES)
_CAT_SET = set(CATEGORIES)


def normalize_org_type(value: str | None, default: str = "other") -> str:
    if value and value.strip().lower() in _ORG_SET:
        return value.strip().lower()
    return default


def normalize_category(value: str | None) -> str | None:
    if value and value.strip().lower() in _CAT_SET:
        return value.strip().lower()
    return None


def category_from_label(label: str | None) -> str | None:
    """Map a portal-provided category label onto the fixed vocab.

    e.g. "Services" -> services, "Consultancy Services" -> consultancy,
    "Civil Works" -> works, item labels ("Electrical Items") -> goods.
    """
    if not label:
        return None
    normalized = normalize_category(label)
    if normalized:
        return normalized
    text = label.strip().lower()
    if not text:
        return None
    if "consult" in text:
        return "consultancy"
    if "service" in text:
        return "services"
    if "work" in text or "construction" in text or "civil" in text:
        return "works"
    # Portal item-type labels (e.g. "Electrical Items", "Clothing/Uniform")
    # describe physical procurement -> goods.
    return "goods"


def normalize_sector_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for v in values:
        key = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        if key in _SECTOR_SET and key not in out:
            out.append(key)
    return out
