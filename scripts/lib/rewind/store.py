"""Rewind store: LRU cache for original text, enabling reversible compression.

Part of claw-compactor. License: MIT.
"""
from __future__ import annotations
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CacheEntry:
    original: str
    compressed: str
    stored_at: float
    original_tokens: int
    compressed_tokens: int


class RewindStore:
    """LRU store mapping hash IDs to original text for later retrieval."""

    def __init__(self, max_entries: int = 500, ttl_seconds: int = 600):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

    def store(self, original: str, compressed: str,
              original_tokens: int = 0, compressed_tokens: int = 0) -> str:
        """Store original text and return a 24-char hex hash ID."""
        hash_id = hashlib.sha256(original.encode("utf-8")).hexdigest()[:24]
        entry = CacheEntry(
            original=original,
            compressed=compressed,
            stored_at=time.monotonic(),
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
        )
        # Move to end (most recently used)
        if hash_id in self._cache:
            self._cache.move_to_end(hash_id)
        self._cache[hash_id] = entry
        # Evict oldest if over limit
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return hash_id

    def retrieve(self, hash_id: str) -> Optional[str]:
        """Retrieve original text by hash ID. Returns None if expired or missing."""
        entry = self._cache.get(hash_id)
        if entry is None:
            return None
        if time.monotonic() - entry.stored_at > self.ttl_seconds:
            del self._cache[hash_id]
            return None
        self._cache.move_to_end(hash_id)
        return entry.original

    def search(self, hash_id: str, keywords: list[str]) -> Optional[str]:
        """Retrieve and filter original text by keywords. Returns matching lines."""
        original = self.retrieve(hash_id)
        if original is None:
            return None
        if not keywords:
            return original
        lines = original.split("\n")
        matched = [l for l in lines if any(kw.lower() in l.lower() for kw in keywords)]
        return "\n".join(matched) if matched else original

    @property
    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()
