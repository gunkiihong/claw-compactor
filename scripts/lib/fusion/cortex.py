"""Cortex — intelligent content router for the Fusion Pipeline.

Runs first (order=5) and detects content_type + language, propagating
them into FusionContext so downstream stages can make type-aware decisions.

Part of claw-compactor. License: MIT.
"""
from __future__ import annotations

from lib.fusion.base import FusionContext, FusionResult, FusionStage
from lib.fusion.content_detector import ContentDetector
from lib.tokens import estimate_tokens


class Cortex(FusionStage):
    """Intelligent content router. Detects content type and routes to appropriate compressors."""

    name = "cortex"
    order = 5  # must run before all compressor stages

    def __init__(self) -> None:
        self.detector = ContentDetector()

    def should_apply(self, ctx: FusionContext) -> bool:
        # Skip if a caller has already made an explicit type decision (non-default value).
        return ctx.content_type == "text"

    def apply(self, ctx: FusionContext) -> FusionResult:
        detection = self.detector.detect(ctx.content)
        tokens = estimate_tokens(ctx.content)

        context_updates: dict[str, object] = {
            "content_type": detection.content_type,
        }
        if detection.language is not None:
            context_updates["language"] = detection.language

        return FusionResult(
            content=ctx.content,
            original_tokens=tokens,
            compressed_tokens=tokens,  # Cortex never modifies content
            skipped=False,
            context_updates=context_updates,
        )
