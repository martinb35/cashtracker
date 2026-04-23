"""Category configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_NAME = "categories.yaml"

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "groceries": [
        "grocery", "supermarket", "whole foods", "trader joe", "kroger", "aldi", "publix",
        "safeway", "costco", "sam's club", "winco", "fred meyer", "qfc", "haggen",
        "sprouts", "h-e-b", "heb", "meijer", "food lion", "piggly wiggly",
        "albertsons", "vons", "ralphs", "wegmans", "stop & shop", "giant",
    ],
    "dining": [
        "restaurant", "cafe", "coffee", "mcdonald", "starbucks", "doordash", "grubhub", "uber eats",
        "chick-fil-a", "chipotle", "subway", "wendy", "burger king", "taco bell", "panda express",
        "domino", "pizza hut", "papa john", "five guys", "in-n-out", "jack in the box",
        "denny", "ihop", "applebee", "olive garden", "red lobster", "outback",
        "panera", "dunkin", "dutch bros", "peet's", "tim horton",
        "postmates", "seamless", "caviar", "gopuff",
        "brewing", "brewery", "taproom", "pub", "bar & grill", "tavern",
        "bakery", "deli", "bistro", "grill", "kitchen", "eatery",
    ],
    "utilities": [
        "electric", "gas", "water", "internet", "phone", "utility",
        "comcast", "verizon", "at&t", "t-mobile", "sprint", "xfinity",
        "spectrum", "cox", "centurylink", "frontier", "att",
        "pge", "pg&e", "duke energy", "con edison", "dominion energy",
        "sewer", "trash", "waste", "garbage",
    ],
    "transportation": [
        "gas station", "fuel", "uber", "lyft", "parking", "toll", "transit",
        "shell", "chevron", "exxon", "mobil", "bp", "arco", "76",
        "costco gas", "safeway fuel", "fred meyer fuel",
        "metro", "bus", "train", "amtrak", "greyhound", "ferry",
    ],
    "entertainment": [
        "netflix", "spotify", "hulu", "movie", "theater", "gaming", "steam",
        "disney+", "disney plus", "hbo", "max", "peacock", "paramount",
        "apple tv", "youtube", "twitch", "xbox", "playstation", "nintendo",
        "amc", "regal", "cinemark", "fandango",
        "ticketmaster", "stubhub", "livenation", "concert", "event",
    ],
    "healthcare": [
        "pharmacy", "doctor", "medical", "dental", "hospital", "cvs", "walgreens",
        "rite aid", "kaiser", "labcorp", "quest diagnostics",
        "optometrist", "vision", "eyecare", "urgent care", "clinic",
        "therapist", "counseling", "mental health",
    ],
    "subscriptions": [
        "subscription", "membership", "annual fee", "monthly fee",
        "adobe", "microsoft 365", "google storage", "icloud",
        "dropbox", "github", "openai", "chatgpt",
        "gym", "fitness", "planet fitness", "24 hour",
    ],
    "shopping": [
        "amazon", "walmart", "target", "ebay", "etsy",
        "best buy", "home depot", "lowe's", "lowes", "ikea",
        "nordstrom", "macy", "ross", "tj maxx", "marshalls",
        "nike", "adidas", "old navy", "gap", "h&m", "zara",
        "bath & body", "sephora", "ulta",
        "play it again", "goodwill", "thrift",
    ],
    "income": [
        "payroll", "direct deposit", "salary", "wage", "dividend", "interest income",
        "payment thank you", "autopay", "automatic payment",
    ],
    "transfers": [
        "transfer", "zelle", "venmo", "paypal", "wire",
        "cash app", "square cash", "wise", "remitly",
    ],
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

    categories: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_CATEGORIES.items()})
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


def save_learned_keywords(
    learned: dict[str, list[str]],
    path: Path | None = None,
) -> Path:
    """Merge learned keywords into an existing categories config file.

    If the file doesn't exist, creates it with defaults + learned keywords.
    """
    if path is None:
        path = Path(DEFAULT_CONFIG_NAME)

    # Load existing config or start from defaults
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            raw = {}
    else:
        raw = {}

    categories = raw.get("categories", dict(DEFAULT_CATEGORIES))

    for category, new_keywords in learned.items():
        existing = categories.get(category, [])
        if existing is None:
            existing = []
        existing_lower = {k.lower() for k in existing}
        for kw in new_keywords:
            if kw.lower() not in existing_lower:
                existing.append(kw)
        categories[category] = existing

    raw["categories"] = categories
    if "ollama" not in raw:
        raw["ollama"] = {
            "model": "llama3.2",
            "base_url": "http://localhost:11434",
            "timeout": 30.0,
            "num_gpu": -1,
            "max_batch_size": 10,
        }

    path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return path
