"""Transform Pipeline framework for Claw Compactor v7.0.

Part of claw-compactor. License: MIT.
"""
from lib.transforms.base import Transform, CompressContext, TransformResult
from lib.transforms.pipeline import Pipeline, PipelineResult

__all__ = [
    "Transform",
    "Pipeline",
    "CompressContext",
    "TransformResult",
    "PipelineResult",
]
