"""Layered transaction categorizer — keyword rules first, Ollama for unknowns."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from cashtracker.config import Config
from cashtracker.models import Transaction

logger = logging.getLogger(__name__)


def categorize_transactions(
    transactions: list[Transaction],
    config: Config,
    use_ai: bool = True,
) -> list[Transaction]:
    """Categorize transactions using a layered approach.

    1. Keyword/rule matching from config (fast, deterministic)
    2. Ollama LLM for unmatched transactions (if use_ai=True)
    """
    unmatched = []

    for txn in transactions:
        category = _match_keywords(txn.raw_description, config.categories)
        if category:
            txn.category = category
            txn.confidence = 1.0
        else:
            unmatched.append(txn)

    if unmatched and use_ai:
        _categorize_with_ollama(unmatched, config)

    return transactions


def _match_keywords(description: str, categories: dict[str, list[str]]) -> str | None:
    """Match a transaction description against category keywords."""
    desc_lower = description.lower()
    for category, keywords in categories.items():
        if category == "uncategorized":
            continue
        for keyword in keywords:
            if keyword.lower() in desc_lower:
                return category
    return None


def _categorize_with_ollama(transactions: list[Transaction], config: Config) -> None:
    """Send unmatched transactions to Ollama for categorization."""
    category_names = [c for c in config.category_names if c != "uncategorized"]
    batch_size = config.ollama.max_batch_size

    for i in range(0, len(transactions), batch_size):
        batch = transactions[i : i + batch_size]
        try:
            _categorize_batch(batch, category_names, config)
        except Exception as e:
            logger.warning("Ollama categorization failed for batch %d: %s", i // batch_size, e)
            for txn in batch:
                if txn.category == "uncategorized":
                    txn.confidence = 0.0


def _categorize_batch(
    transactions: list[Transaction],
    category_names: list[str],
    config: Config,
) -> None:
    """Categorize a single batch via Ollama."""
    descriptions = []
    for i, txn in enumerate(transactions):
        descriptions.append(f"{i + 1}. {txn.raw_description} (${txn.amount})")

    prompt = _build_prompt(descriptions, category_names)

    response = _call_ollama(prompt, config)
    results = _parse_response(response, category_names)

    for i, txn in enumerate(transactions):
        if i < len(results):
            txn.category = results[i]
            txn.confidence = 0.8
        else:
            txn.category = "uncategorized"
            txn.confidence = 0.0


def _build_prompt(descriptions: list[str], category_names: list[str]) -> str:
    """Build the categorization prompt."""
    cats = ", ".join(category_names)
    txns = "\n".join(descriptions)

    return (
        f"Categorize each transaction into exactly one of these categories: {cats}\n\n"
        f"Transactions:\n{txns}\n\n"
        "Respond with ONLY a JSON array of category strings, one per transaction, in order. "
        "Example: [\"groceries\", \"dining\", \"utilities\"]\n"
        "Do not include any explanation or extra text."
    )


def _call_ollama(prompt: str, config: Config) -> str:
    """Call the Ollama generate API."""
    url = f"{config.ollama.base_url}/api/generate"
    payload: dict[str, Any] = {
        "model": config.ollama.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_gpu": config.ollama.num_gpu,
        },
    }

    try:
        resp = httpx.post(url, json=payload, timeout=config.ollama.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except httpx.ConnectError:
        raise RuntimeError(
            "Cannot connect to Ollama. Is it running? Start it with: ollama serve"
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama request timed out after {config.ollama.timeout}s. "
            "Try increasing timeout in categories.yaml or use --no-ai"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama API error: {e.response.status_code} {e.response.text}")


def _parse_response(response: str, allowed_categories: list[str]) -> list[str]:
    """Parse and validate Ollama's JSON response."""
    response = response.strip()

    # Try to extract JSON array from response
    start = response.find("[")
    end = response.rfind("]")
    if start == -1 or end == -1:
        logger.warning("Ollama response is not a JSON array: %s", response[:200])
        return []

    try:
        results = json.loads(response[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Failed to parse Ollama JSON response: %s", response[:200])
        return []

    if not isinstance(results, list):
        return []

    # Validate each category
    validated = []
    allowed_lower = {c.lower(): c for c in allowed_categories}
    for item in results:
        item_str = str(item).lower().strip()
        if item_str in allowed_lower:
            validated.append(allowed_lower[item_str])
        else:
            validated.append("uncategorized")

    return validated
