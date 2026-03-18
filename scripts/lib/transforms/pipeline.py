"""Pipeline engine: runs a chain of Transforms sequentially.

Part of claw-compactor. License: MIT.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from lib.transforms.base import Transform, CompressContext, TransformResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepResult:
    """Result from a single pipeline step."""
    transform_name: str
    result: TransformResult


@dataclass(frozen=True)
class PipelineResult:
    """Aggregated result from running all transforms."""
    content: str
    steps: list[StepResult] = field(default_factory=list)
    total_timing_ms: float = 0.0
    markers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Pipeline:
    """Ordered chain of Transforms."""

    def __init__(self, transforms: list[Transform] | None = None):
        self._transforms: list[Transform] = sorted(
            transforms or [], key=lambda t: t.order
        )

    def add(self, transform: Transform) -> Pipeline:
        """Return a new Pipeline with the transform added (immutable)."""
        new_transforms = sorted(
            [*self._transforms, transform], key=lambda t: t.order
        )
        return Pipeline(new_transforms)

    @property
    def transforms(self) -> list[Transform]:
        return list(self._transforms)

    def run(self, ctx: CompressContext) -> PipelineResult:
        """Run all transforms sequentially. Each transform's output feeds the next."""
        steps: list[StepResult] = []
        all_markers: list[str] = []
        all_warnings: list[str] = []
        total_ms = 0.0
        current_ctx = ctx

        for transform in self._transforms:
            result = transform.timed_apply(current_ctx)
            steps.append(StepResult(
                transform_name=transform.name,
                result=result,
            ))
            total_ms += result.timing_ms

            if not result.skipped:
                current_ctx = current_ctx.evolve(content=result.content)
                all_markers.extend(result.markers)
                all_warnings.extend(result.warnings)
                logger.debug(
                    "%s: %d→%d tokens (%.1fms)",
                    transform.name,
                    result.original_tokens,
                    result.compressed_tokens,
                    result.timing_ms,
                )
            else:
                logger.debug("%s: skipped", transform.name)

        return PipelineResult(
            content=current_ctx.content,
            steps=steps,
            total_timing_ms=total_ms,
            markers=all_markers,
            warnings=all_warnings,
        )
