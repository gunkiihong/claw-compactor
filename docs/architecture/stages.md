# Stage Reference

Detailed reference for each of the 14 Fusion Pipeline stages.

## Creating a Custom Stage

```python
from scripts.lib.fusion.base import FusionStage, FusionContext, FusionResult

class MyStage(FusionStage):
    name = "my_compressor"
    order = 22  # between StructuralCollapse (20) and Neurosyntax (25)

    def should_apply(self, ctx: FusionContext) -> bool:
        return ctx.content_type == "log"

    def apply(self, ctx: FusionContext) -> FusionResult:
        compressed = my_compression_logic(ctx.content)
        return FusionResult(
            content=compressed,
            original_tokens=estimate_tokens(ctx.content),
            compressed_tokens=estimate_tokens(compressed),
        )
```

## Stage API

### `FusionStage` (abstract base)

| Attribute/Method | Type | Description |
|:----------------|:-----|:-----------|
| `name` | `str` | Unique stage identifier |
| `order` | `int` | Execution order (lower = earlier) |
| `should_apply(ctx)` | `bool` | Gate: return False to skip this stage |
| `apply(ctx)` | `FusionResult` | Core compression logic |

### `FusionContext` (frozen dataclass)

| Field | Type | Description |
|:------|:-----|:-----------|
| `content` | `str` | Current text being processed |
| `content_type` | `str \| None` | Detected type: code, json, log, diff, search, text |
| `language` | `str \| None` | Detected programming language |
| `role` | `str \| None` | Message role: system, user, assistant, tool |

### `FusionResult`

| Field | Type | Description |
|:------|:-----|:-----------|
| `content` | `str` | Compressed output |
| `original_tokens` | `int` | Token count before compression |
| `compressed_tokens` | `int` | Token count after compression |
| `markers` | `list` | Rewind markers (if reversible) |
