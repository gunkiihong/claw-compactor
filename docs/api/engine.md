# FusionEngine API

The main entry point for Claw Compactor.

## Constructor

```python
from scripts.lib.fusion.engine import FusionEngine

engine = FusionEngine(
    enable_rewind=False,  # Enable reversible compression
)
```

## Methods

### `compress(text, content_type=None, language=None)`

Compress a single text through the full 14-stage pipeline.

```python
result = engine.compress(
    text="def hello():\n    print('hello')",
    content_type="code",     # optional, Cortex auto-detects
    language="python",       # optional hint
)
```

**Returns:** `dict` with keys:
- `compressed` — compressed text
- `stats` — per-stage timing and token counts
- `markers` — Rewind markers (if enabled)

### `compress_messages(messages)`

Compress a list of chat messages. Runs cross-message deduplication first, then per-message pipeline.

```python
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
]
result = engine.compress_messages(messages)
```

**Returns:** `dict` with keys:
- `stats` — aggregate statistics
- `per_message` — per-message breakdown
