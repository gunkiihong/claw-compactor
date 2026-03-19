# Stage APIs

Each stage follows the same interface. See [Stage Reference](../architecture/stages.md) for the base class documentation.

## Stage-Specific Configuration

### Ionizer (JSON Sampling)

```python
# Ionizer samples large JSON arrays, keeping schema + statistical summary
# Default: keeps first 2 items + error items + schema
```

### Neurosyntax (AST Code Compression)

```python
# Uses tree-sitter when available, falls back to safe regex
# Never shortens identifiers — preserves all names
# Supports 63 languages via tree-sitter-language-pack
```

### QuantumLock (KV-Cache Alignment)

```python
# Isolates dynamic content in system prompts
# Stabilizes prefix for KV-cache hit optimization
```

### Abbrev (Natural Language)

```python
# Only fires on text content type
# Never touches code, JSON, or structured data
# Common abbreviations: "information" → "info", etc.
```
