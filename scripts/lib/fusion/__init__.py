"""Fusion Pipeline framework for Claw Compactor v7.0.

Part of claw-compactor. License: MIT.
"""
from lib.fusion.base import FusionStage, FusionContext, FusionResult
from lib.fusion.pipeline import FusionPipeline, FusionPipelineResult

__all__ = [
    "FusionStage",
    "FusionPipeline",
    "FusionContext",
    "FusionResult",
    "FusionPipelineResult",
]
