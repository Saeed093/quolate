"""Pakistan import duty/tax calculation engine (Customs Duty, Additional
Customs Duty, Regulatory Duty, Sales Tax, Federal Excise Duty, and advance
Income Tax withholding under Section 148).

- `engine.py`   -- pure Decimal arithmetic, no I/O, exhaustively unit-tested.
- `resolver.py` -- DB-backed rate + exemption lookup (date-versioned).
- `calculator.py` -- ties the two together for API/consumers.
- `schemas.py`  -- Pydantic models for the calculation result and rate rows.
"""
