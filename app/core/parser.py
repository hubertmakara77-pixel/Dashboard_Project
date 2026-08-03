"""Compatibility imports for the amplifier protocol adapter.

New code should import :mod:`app.protocols.amplifier` directly. This module keeps
the previous import path available without duplicating firmware knowledge.
"""

from app.protocols.amplifier import parse_line

__all__ = ["parse_line"]
