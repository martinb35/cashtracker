# CashTracker

A local-only CLI tool for parsing bank and credit card statements, categorizing transactions into user-defined buckets, and exporting the results to CSV.

**Your transaction data never leaves your PC.** Categorization uses [Ollama](https://ollama.com/) running locally with NVIDIA GPU acceleration.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com/) installed and running (for AI categorization)
- NVIDIA GPU recommended (Ollama uses CUDA automatically)

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

1. Create a categories config:
   ```bash
   cashtracker config init
   ```

2. Parse a bank statement:
   ```bash
   cashtracker parse statement.csv
   ```

3. Output is written to CSV with columns: `date`, `category`, `amount`, `vendor/company/item`

## CLI Commands

```bash
cashtracker parse <file>          # Parse and categorize a statement
cashtracker parse <file> --no-ai  # Skip Ollama, use keyword rules only
cashtracker parse <file> --output out.csv --model llama3.2
cashtracker config init           # Create default categories.yaml
cashtracker config show           # Display current categories
```

## How It Works

1. **Read** — Detects file format (CSV or PDF) and extracts raw data
2. **Parse** — Institution-aware normalizer converts raw data into transactions
3. **Categorize** — Keyword rules match first; Ollama handles the rest
4. **Export** — Results written to CSV
