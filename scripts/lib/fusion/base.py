"""Fusion stage base classes for Claw Compactor pipeline.

Part of claw-compactor. License: MIT.
"""
from __future__ import annotations
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class FusionContext:
    """Immutable context passed through the fusion pipeline."""
    content: str
    content_type: str = "text"  # text|code|json|log|diff|search
    language: str | None = None
    role: str = "user"  # system|user|assistant|tool
    model: str | None = None
    token_budget: int | None = None
    query: str | None = None
    metadata: dict = field(default_factory=dict)

    def evolve(self, **kwargs) -> FusionContext:
        """Return a new context with specified fields replaced."""
        return replace(self, **kwargs)


@dataclass(frozen=True)
class FusionResult:
    """Immutable result from a single fusion stage."""
    content: str
    original_tokens: int = 0
    compressed_tokens: int = 0
    markers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timing_ms: float = 0.0
    skipped: bool = False
    # Optional overrides applied to FusionContext after this stage runs.
    # Keys must match FusionContext field names (e.g. content_type, language).
    context_updates: dict[str, Any] = field(default_factory=dict)


class FusionStage(ABC):
    """Base class for all compression fusion stages."""
    name: str = "unnamed"
    order: int = 50  # execution order (lower = earlier)

    @abstractmethod
    def should_apply(self, ctx: FusionContext) -> bool:
        """Return True if this fusion stage should run on the given context."""
        ...

    @abstractmethod
    def apply(self, ctx: FusionContext) -> FusionResult:
        """Apply the fusion stage and return the result."""
        ...

    def timed_apply(self, ctx: FusionContext) -> FusionResult:
        """Apply with timing. Used by FusionPipeline."""
        if not self.should_apply(ctx):
            return FusionResult(content=ctx.content, skipped=True)
        start = time.monotonic()
        result = self.apply(ctx)
        elapsed = (time.monotonic() - start) * 1000
        return FusionResult(
            content=result.content,
            original_tokens=result.original_tokens,
            compressed_tokens=result.compressed_tokens,
            markers=result.markers,
            warnings=result.warnings,
            timing_ms=elapsed,
            skipped=False,
            context_updates=result.context_updates,
        )
