"""Memory filtering helpers."""

from __future__ import annotations

import re

_PROFILE_MEMORY_PATTERN = re.compile(r"^(name|display\s+name|email)\s+is\b", re.IGNORECASE)


def is_profile_identity_memory(memory_text: str) -> bool:
    """Return True when memory text represents profile identity/contact facts.

    These facts should come from the live auth profile (e.g. get_user_contact)
    instead of long-term memory, which can be stale.
    """
    normalized = (memory_text or "").strip()
    if not normalized:
        return False
    return bool(_PROFILE_MEMORY_PATTERN.match(normalized))
