"""SnapBack reversible compression engine for Claw Compactor v7.0.

Part of claw-compactor. License: MIT.
"""
from .store import SnapBackStore
from .marker import embed_marker, extract_markers, has_markers
from .retriever import snapback_tool_def, handle_retrieval

__all__ = [
    "SnapBackStore",
    "embed_marker",
    "extract_markers",
    "has_markers",
    "snapback_tool_def",
    "handle_retrieval",
]
