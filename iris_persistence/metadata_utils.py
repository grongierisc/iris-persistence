from __future__ import annotations

from typing import Any


def coerce_bool(value: Any) -> bool:
    return value == 1 or value == "1" or str(value).lower() == "true"
