# CashTracker - Copilot Instructions

## Build & Test Commands

```bash
# Install (editable with dev dependencies)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_categorizer.py

# Run a single test
pytest tests/test_categorizer.py::TestMatchKeywords::test_match_found -v

# Run with coverage
pytest --cov=cashtracker
```

## Architecture

CashTracker is a CLI tool that parses bank/credit card statements and categorizes transactions using a layered approach (keyword rules first, Ollama LLM for unknowns).

### Pipeline

```
Input file → File reader → Parser registry → Normalizer → Categorizer → CSV output
```

### Key components

- **Readers** (`src/cashtracker/readers/`) — Format-specific file ingestion. `csv_reader` auto-detects delimiters/encoding. `pdf_reader` extracts tables from text-based PDFs (scanned PDFs raise `ScannedPDFError`).
- **Parsers** (`src/cashtracker/parsers/`) — Institution-centric normalization. Each normalizer implements `StatementNormalizer` with `can_handle()` returning a confidence score (0.0–1.0) and `normalize()` producing a `ParsedStatement`. The registry scores all normalizers and picks the best. `GenericCSVNormalizer` is the fallback for unrecognized CSV formats.
- **Categorizer** (`src/cashtracker/categorizer.py`) — Layered: keyword rules from config match first (confidence=1.0), then Ollama handles unknowns. Ollama output is strictly validated—only categories from the user's config are accepted, responses must be valid JSON.
- **Config** (`src/cashtracker/config.py`) — YAML-based. Categories map to keyword lists. Ollama settings include `num_gpu` for NVIDIA GPU acceleration (-1 = all layers on GPU).

### Data model

`Transaction` is richer than the output CSV—it carries `raw_description`, `normalized_vendor`, `confidence`, `source_file`, etc. for debugging and future features. Output CSV is always: `date, category, amount, vendor/company/item`.

## Conventions

- **Adding a new bank format**: Create a new `StatementNormalizer` subclass in `src/cashtracker/parsers/`, implement `can_handle()` and `normalize()`, and register it in `registry.py`'s `_NORMALIZERS` list.
- **Ollama integration**: All LLM calls go through `categorizer.py`. Responses are validated against the config's category list. The `num_gpu` option is passed to Ollama for GPU offloading.
- **Transaction model**: Use `raw_description` for the original text, `normalized_vendor` for cleaned-up display. `vendor_display` property handles the fallback.
- **Error handling**: Parsers collect warnings in `ParsedStatement.warnings` rather than raising on individual row failures. Only fatal issues (wrong format, scanned PDF) raise exceptions.
