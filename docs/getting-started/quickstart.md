# Quick Start

## CLI Usage

```bash
# Benchmark your workspace (non-destructive dry run)
claw-compactor benchmark /path/to/workspace

# Full compression pipeline
claw-compactor compress /path/to/workspace
```

## Python API

### Compress a single text

```python
from scripts.lib.fusion.engine import FusionEngine

engine = FusionEngine()

result = engine.compress(
    text="def hello():\n    # greeting function\n    print('hello')",
    content_type="code",
    language="python",
)

print(result["compressed"])     # compressed output
print(result["stats"])          # per-stage timing + token counts
```

### Compress chat messages

```python
messages = [
    {"role": "system", "content": "You are a coding assistant..."},
    {"role": "user", "content": "Fix the auth bug in login.py"},
    {"role": "assistant", "content": "I found the issue..."},
    {"role": "tool", "content": '{"results": [...]}'},
]

result = engine.compress_messages(messages)
print(f"Reduction: {result['stats']['reduction_pct']:.1f}%")
```

### Reversible compression

```python
engine = FusionEngine(enable_rewind=True)
result = engine.compress(large_json, content_type="json")

# LLM sees markers like [rewind:abc123...]
# Retrieve the original when needed:
original = engine.rewind_store.retrieve("abc123def456...")
```

## Available Commands

| Command | Description |
|:--------|:-----------|
| `benchmark` | Dry-run compression report |
| `compress` | Full compression pipeline |
| `dict` | Dictionary encoding with auto-learned codebook |
| `observe` | Session transcript to structured observations |
| `tiers` | Generate L0/L1/L2 tiered summaries |
| `dedup` | Cross-file duplicate detection |
| `estimate` | Token count report |
| `audit` | Workspace health check |
| `optimize` | Tokenizer-level format optimization |
| `auto` | Watch mode — compress on file changes |
