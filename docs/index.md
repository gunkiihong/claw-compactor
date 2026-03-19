# Claw Compactor

## 14-Stage Fusion Pipeline for LLM Token Compression

**15–82% compression depending on content · Zero LLM inference cost · Reversible · 1600+ tests**

---

## What is Claw Compactor?

Claw Compactor is an open-source **LLM token compression engine** built around a 14-stage **Fusion Pipeline**. Each stage is a specialized compressor — from AST-aware code analysis to JSON statistical sampling to simhash-based deduplication — chained through an immutable data flow architecture.

## Why?

LLM context windows are expensive. Every token costs money and consumes limited context. Claw Compactor reduces token count by 15–82% **without calling an LLM** — pure deterministic compression that preserves semantic meaning.

## Key Features

- **14 specialized compression stages** — each tuned for a content type (code, JSON, logs, diffs, search results, natural language)
- **Zero LLM inference cost** — all compression is deterministic, no API calls needed
- **Reversible compression** — Ionizer stores originals with hash-addressed markers for on-demand retrieval
- **Content-aware routing** — Cortex auto-detects content type and language, downstream stages adapt
- **Zero required dependencies** — runs with Python 3.9+ stdlib; tiktoken and tree-sitter are optional

## Quick Install

```bash
pip install claw-compactor
```

Or from source:

```bash
git clone https://github.com/open-compress/claw-compactor.git
cd claw-compactor
pip install -e .
```

## Quick Example

```python
from scripts.lib.fusion.engine import FusionEngine

engine = FusionEngine()
result = engine.compress(
    text="def hello():\n    # greeting function\n    print('hello')",
    content_type="code",
    language="python",
)
print(f"Compressed: {result['stats']['reduction_pct']:.1f}%")
```

## Links

- [GitHub Repository](https://github.com/open-compress/claw-compactor)
- [Architecture Deep-Dive](architecture/overview.md)
- [Benchmarks](benchmarks.md)
- [Discord Community](https://discord.com/invite/clawd)
