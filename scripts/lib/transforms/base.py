"""Transform base classes for Claw Compactor pipeline.

Part of claw-compactor. License: MIT.
"""
from __future__ import annotations
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class CompressContext:
    """Immutable context passed through the transform pipeline."""
    content: str
    content_type: str = "text"  # text|code|json|log|diff|search
    language: str | None = None
    role: str = "user"  # system|user|assistant|tool
    model: str | None = None
    token_budget: int | None = None
    query: str | None = None
    metadata: dict = field(default_factory=dict)

    def evolve(self, **kwargs) -> CompressContext:
        """Return a new context with specified fields replaced."""
        return replace(self, **kwargs)


@dataclass(frozen=True)
class TransformResult:
    """Immutable result from a single transform."""
    content: str
    original_tokens: int = 0
    compressed_tokens: int = 0
    markers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timing_ms: float = 0.0
    skipped: bool = False


class Transform(ABC):
    """Base class for all compression transforms."""
    name: str = "unnamed"
    order: int = 50  # execution order (lower = earlier)

    @abstractmethod
    def should_apply(self, ctx: CompressContext) -> bool:
        """Return True if this transform should run on the given context."""
        ...

    @abstractmethod
    def apply(self, ctx: CompressContext) -> TransformResult:
        """Apply the transform and return the result."""
        ...

    def timed_apply(self, ctx: CompressContext) -> TransformResult:
        """Apply with timing. Used by Pipeline."""
        if not self.should_apply(ctx):
            return TransformResult(content=ctx.content, skipped=True)
        start = time.monotonic()
        result = self.apply(ctx)
        elapsed = (time.monotonic() - start) * 1000
        return TransformResult(
            content=result.content,
            original_tokens=result.original_tokens,
            compressed_tokens=result.compressed_tokens,
            markers=result.markers,
            warnings=result.warnings,
            timing_ms=elapsed,
            skipped=False,
        )
