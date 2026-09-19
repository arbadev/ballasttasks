"""Provider-neutral keys: relative ASCII segments, never client paths."""

import re

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def valid_storage_key(key: str) -> bool:
    return len(key) <= 200 and _KEY.fullmatch(key) is not None
