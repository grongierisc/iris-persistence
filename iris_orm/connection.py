"""
Compatibility wrapper around the embedded IRIS adapter.
"""
from __future__ import annotations

from .adapter import IRISAdapter


class IRISConnection(IRISAdapter):
    """Backward-compatible alias for the internal embedded IRIS adapter."""

