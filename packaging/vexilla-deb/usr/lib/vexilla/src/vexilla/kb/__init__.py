"""Knowledge base — offline domain lookup.

Read-only access to the shipped kb.db plus build tools.
"""

from vexilla.kb.reader import KbReader, DomainInfo, CATEGORIES

__all__ = ["KbReader", "DomainInfo", "CATEGORIES"]
