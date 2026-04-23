"""Category configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_NAME = "categories.yaml"

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "groceries": ["grocery", "supermarket", "whole foods", "trader joe", "kroger", "aldi", "publix"],
    "dining": ["restaurant", "cafe", "coffee", "mcdonald", "starbucks", "doordash", "grubhub", "uber eats"],
    "utilities": ["electric", "gas", "water", "internet", "phone", "utility", "comcast", "verizon", "at&t"],
    "transportation": ["gas station", "fuel", "uber", "lyft", "parking", "toll", "transit"],
    "entertainment": ["netflix", "spotify", "hulu", "movie", "theater", "gaming", "steam"],
    "healthcare": ["pharmacy", "doctor", "medical", "dental", "hospital", "cvs", "walgreens"],
    "subscriptions": ["subscription", "membership", "annual fee", "monthly fee"],
    "shopping": ["amazon", "walmart", "target", "ebay", "etsy"],
    "income": ["payroll", "direct deposit", "salary", "wage", "dividend", "interest income"],
    "transfers": ["transfer", "zelle", "venmo", "paypal", "wire"],
    "uncategorized": [],
}


@dataclass
class OllamaConfig:
    """Ollama API settings."""

    model: str = "llama3.2"
    base_url: str = "http://localhost:11434"
    timeout: float = 30.0
    num_gpu: int = -1  # -1 = all layers on GPU
    max_batch_size: int = 10


@dataclass
class Config:
    """Application configuration."""

    categories: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_CATEGORIES))
    ollama: OllamaConfig = field(default_factory=OllamaConfig)

    @property
    def category_names(self) -> list[str]:
        return list(self.categories.keys())


def load_config(path: Path | None = None) -> Config:
    """Load configuration from a YAML file.

    Falls back to defaults if the file doesn't exist.
    """
    if path is None:
        path = Path(DEFAULT_CONFIG_NAME)

    if not path.exists():
        return Config()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError(f"Expected a mapping in {path}, got {type(raw).__name__}")

    return _parse_config(raw)


def _parse_config(raw: dict[str, Any]) -> Config:
    """Parse raw YAML dict into a Config."""
    config = Config()

    if "categories" in raw:
        cats = raw["categories"]
        if not isinstance(cats, dict):
            raise ValueError("'categories' must be a mapping of category name to keyword list")
        config.categories = {}
        for name, keywords in cats.items():
            if keywords is None:
                keywords = []
            if not isinstance(keywords, list):
                raise ValueError(f"Keywords for category '{name}' must be a list")
            config.categories[str(name)] = [str(k) for k in keywords]

        if "uncategorized" not in config.categories:
            config.categories["uncategorized"] = []

    if "ollama" in raw:
        oll = raw["ollama"]
        if isinstance(oll, dict):
            config.ollama = OllamaConfig(
                model=str(oll.get("model", config.ollama.model)),
                base_url=str(oll.get("base_url", config.ollama.base_url)),
                timeout=float(oll.get("timeout", config.ollama.timeout)),
                num_gpu=int(oll.get("num_gpu", config.ollama.num_gpu)),
                max_batch_size=int(oll.get("max_batch_size", config.ollama.max_batch_size)),
            )

    return config


def write_default_config(path: Path | None = None) -> Path:
    """Write the default configuration to a YAML file."""
    if path is None:
        path = Path(DEFAULT_CONFIG_NAME)

    data: dict[str, Any] = {
        "categories": DEFAULT_CATEGORIES,
        "ollama": {
            "model": "llama3.2",
            "base_url": "http://localhost:11434",
            "timeout": 30.0,
            "num_gpu": -1,
            "max_batch_size": 10,
        },
    }

    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return path
