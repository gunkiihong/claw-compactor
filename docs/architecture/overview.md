# Architecture Overview

Claw Compactor is built around a **14-stage Fusion Pipeline** — a chain of specialized compressors that each handle a specific content type or compression strategy.

## Design Principles

### Immutable Data Flow

Every stage receives a frozen `FusionContext` and produces a new `FusionResult`. Nothing is mutated in-place. This makes stages safe to reorder, parallelize, and test in isolation.

### Gate-Before-Compress

Each stage implements `should_apply(ctx)` that inspects content type, language, and role before doing any work. Stages that don't apply are skipped at zero cost.

### Content-Aware Routing

The **Cortex** stage (order 5) auto-detects content type and programming language. All downstream stages use this classification to make type-aware compression decisions.

### Zero Required Dependencies

The core pipeline runs on Python 3.9+ stdlib alone. Optional dependencies (tiktoken for exact token counts, tree-sitter for AST parsing) are detected at runtime.

## Pipeline Architecture

```
Input → QuantumLock → Cortex → Photon → RLE → SemanticDedup → Ionizer
     → LogCrunch → SearchCrunch → DiffCrunch → StructuralCollapse
     → Neurosyntax → Nexus → TokenOpt → Abbrev → Output

[ RewindStore ] — hash-addressed LRU for reversible retrieval
```

See [Pipeline Details](pipeline.md) for stage-by-stage documentation and [Stage Reference](stages.md) for the API.

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `FusionEngine` | `scripts/lib/fusion/engine.py` | Main entry point, orchestrates pipeline |
| `FusionStage` | `scripts/lib/fusion/base.py` | Abstract base for all stages |
| `FusionContext` | `scripts/lib/fusion/base.py` | Frozen dataclass passed between stages |
| `RewindStore` | `scripts/lib/fusion/rewind.py` | Hash-addressed storage for reversibility |
| `Cortex` | `scripts/lib/fusion/stages/cortex.py` | Content type + language detection |
