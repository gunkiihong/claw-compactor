# Installation

## From PyPI

```bash
pip install claw-compactor
```

## From Source

```bash
git clone https://github.com/open-compress/claw-compactor.git
cd claw-compactor
pip install -e .
```

## Optional Dependencies

```bash
# Exact token counting (recommended)
pip install claw-compactor[accurate]
# or: pip install tiktoken

# AST-aware code compression (Neurosyntax stage)
pip install tree-sitter-language-pack

# All development dependencies
pip install -e ".[dev,accurate]"
```

## Requirements

- Python 3.9+
- No required external dependencies — the core pipeline runs on stdlib alone

## Verify Installation

```bash
python -c "from scripts.lib.fusion.engine import FusionEngine; print('OK')"
```
