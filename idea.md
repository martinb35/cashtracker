# CashTracker

A local-only system for parsing bank and credit card statements, categorizing transactions into user-defined buckets, and exporting the results to CSV. Transaction data never leaves your PC.

## Output Format

CSV with columns: `date`, `category`, `amount`, `vendor/company/item`

## Tech Stack

- **Language:** Python
- **Interface:** CLI (using click)
- **Local AI:** Ollama (e.g. Llama, Mistral) for transaction categorization
- **Statement input:** CSV and text-based PDF (v1)
- **PDF extraction:** pdfplumber
- **Config format:** YAML (user-defined categories with keyword hints)
- **HTTP client:** httpx (for Ollama REST API at localhost:11434)
- **Testing:** pytest

## Architecture

### Parsing Pipeline

```
Input file → File reader → Detect institution/template → Normalize → Categorize → Export CSV
```

Parsing is **institution-centric**, not just format-centric. Two CSV files from different banks can have completely different columns, date formats, and sign conventions. The architecture reflects this:

1. **File readers** — Extract raw rows/text from a file format (CSV loader, PDF text extractor)
2. **Statement normalizers** — Institution-specific mapping into a canonical transaction model
3. **Parser registry** — Selects the correct normalizer based on detected institution/template

### Categorization (Layered)

Categorization uses a layered approach for speed and consistency:

1. **Keyword/rule matching** — Deterministic categorization from user-defined rules in YAML (fast, predictable)
2. **Ollama LLM** — Only used for transactions that don't match any rule (slower, but handles unknowns)

Ollama output is strictly constrained:
- Only allowed category names from the user's config are accepted
- Responses must be valid JSON
- Invalid/hallucinated categories are rejected
- Timeouts, retries, and model-availability checks are handled

### Transaction Model

The internal transaction model is richer than the output CSV to support debugging and future features:

- `transaction_date`, `posted_date`
- `raw_description`, `normalized_vendor`
- `amount`, `currency`
- `source_file`, `account_name`
- `category`, `confidence`

### PDF Support Boundaries (v1)

- Text-based PDFs only
- Scanned/image PDFs are not supported — clear error messages guide the user
- OCR support is a future enhancement

## Planned Project Structure

```
cashtracker/
├── pyproject.toml
├── README.md
├── .gitignore
├── categories.example.yaml
├── src/
│   └── cashtracker/
│       ├── __init__.py
│       ├── cli.py              # CLI entry point (click)
│       ├── config.py           # Category config loading/validation
│       ├── models.py           # Transaction dataclass
│       ├── readers/
│       │   ├── __init__.py
│       │   ├── csv_reader.py   # Raw CSV loading
│       │   └── pdf_reader.py   # PDF text/table extraction
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── base.py         # Abstract normalizer interface
│       │   └── registry.py     # Institution detection and parser selection
│       ├── categorizer.py      # Layered categorization (rules + Ollama)
│       └── output.py           # CSV output writer
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_parsers.py
    ├── test_categorizer.py
    └── test_output.py
```

## CLI Commands

- `cashtracker parse <file>` — Parse a statement, categorize transactions, output CSV
- `cashtracker config init` — Create a default categories config file
- `cashtracker config show` — Show current categories

## Future Considerations

- OFX/QFX format support
- OCR for scanned PDFs
- Transaction deduplication (fingerprint: date + amount + description + source)
- Review/correction loop for miscategorized transactions
- Vendor history cache for improved categorization over time
- Config schema versioning 