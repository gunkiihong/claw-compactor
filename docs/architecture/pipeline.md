# Fusion Pipeline

The Fusion Pipeline chains 14 stages in order. Each stage is independent and communicates only through the immutable `FusionContext`.

## Stage Execution Order

| # | Stage | Order | Purpose | Applies To |
|:-:|:------|:-----:|:--------|:-----------|
| 1 | **QuantumLock** | 3 | Isolates dynamic content in system prompts for KV-cache alignment | system messages |
| 2 | **Cortex** | 5 | Auto-detects content type and programming language (16 languages) | untyped content |
| 3 | **Photon** | 8 | Detects and compresses base64-encoded images | all |
| 4 | **RLE** | 10 | Path shorthand (`$WS`), IP prefix compression, enum compaction | all |
| 5 | **SemanticDedup** | 12 | SimHash fingerprint deduplication across content blocks | all |
| 6 | **Ionizer** | 15 | JSON array statistical sampling with schema discovery + error preservation | json |
| 7 | **LogCrunch** | 16 | Folds repeated log lines with occurrence counts | log |
| 8 | **SearchCrunch** | 17 | Deduplicates search/grep results | search |
| 9 | **DiffCrunch** | 18 | Folds unchanged context lines in git diffs | diff |
| 10 | **StructuralCollapse** | 20 | Merges import blocks, collapses repeated assertions/patterns | code |
| 11 | **Neurosyntax** | 25 | AST-aware code compression via tree-sitter (safe regex fallback) | code |
| 12 | **Nexus** | 35 | ML token-level classification (stopword removal fallback) | text |
| 13 | **TokenOpt** | 40 | Tokenizer format optimization — strips bold/italic, normalizes whitespace | all |
| 14 | **Abbrev** | 45 | Natural language abbreviation. Never touches code/JSON/structured data. | text |

## Execution Model

```python
context = FusionContext(content=input_text, content_type=None)

for stage in sorted(stages, key=lambda s: s.order):
    if stage.should_apply(context):
        result = stage.apply(context)
        context = context.evolve(content=result.content, ...)
```

Each stage's `should_apply()` acts as a gate — if false, the stage is skipped entirely with zero overhead.
