# Rewind API

Reversible compression via hash-addressed storage.

## Overview

When `enable_rewind=True`, the Ionizer stage stores original content in a `RewindStore`. The compressed output contains markers like `[rewind:abc123...]` that the LLM can use to retrieve originals on demand.

## Usage

```python
from scripts.lib.fusion.engine import FusionEngine

engine = FusionEngine(enable_rewind=True)

# Compress — originals stored automatically
result = engine.compress(large_json, content_type="json")

# The LLM sees markers in the compressed output
# When it needs the original:
original = engine.rewind_store.retrieve("abc123def456...")
```

## How It Works

1. **Compress:** Ionizer detects large JSON arrays, samples them, stores the full original
2. **Mark:** A unique hash-based marker replaces the compressed section
3. **Retrieve:** The LLM calls a tool with the marker ID to get the original back
4. **LRU Eviction:** RewindStore uses LRU to manage memory

## RewindStore API

| Method | Description |
|:-------|:-----------|
| `store(content) → marker_id` | Store content, returns marker ID |
| `retrieve(marker_id) → str` | Retrieve stored content by marker |
| `clear()` | Clear all stored content |
| `size` | Number of stored items |
