"""Tests for config loading and validation."""

from pathlib import Path

import pytest
import yaml

from cashtracker.config import Config, OllamaConfig, load_config, write_default_config


class TestLoadConfig:
    def test_defaults_when_no_file(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert "groceries" in cfg.categories
        assert "uncategorized" in cfg.categories
        assert cfg.ollama.model == "llama3.2"
        assert cfg.ollama.num_gpu == -1

    def test_load_custom_categories(self, tmp_path: Path):
        config_path = tmp_path / "categories.yaml"
        config_path.write_text(yaml.dump({
            "categories": {
                "food": ["restaurant", "grocery"],
                "bills": ["electric", "water"],
            }
        }))
        cfg = load_config(config_path)
        assert "food" in cfg.categories
        assert "bills" in cfg.categories
        assert "uncategorized" in cfg.categories  # auto-added

    def test_load_ollama_config(self, tmp_path: Path):
        config_path = tmp_path / "categories.yaml"
        config_path.write_text(yaml.dump({
            "categories": {"food": ["grocery"]},
            "ollama": {
                "model": "mistral",
                "timeout": 60.0,
                "num_gpu": 32,
            },
        }))
        cfg = load_config(config_path)
        assert cfg.ollama.model == "mistral"
        assert cfg.ollama.timeout == 60.0
        assert cfg.ollama.num_gpu == 32

    def test_invalid_yaml_raises(self, tmp_path: Path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("{{{{invalid yaml")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(config_path)

    def test_non_dict_yaml_raises(self, tmp_path: Path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="Expected a mapping"):
            load_config(config_path)

    def test_null_keywords_treated_as_empty(self, tmp_path: Path):
        config_path = tmp_path / "categories.yaml"
        config_path.write_text(yaml.dump({
            "categories": {"misc": None}
        }))
        cfg = load_config(config_path)
        assert cfg.categories["misc"] == []


class TestWriteDefaultConfig:
    def test_creates_file(self, tmp_path: Path):
        path = write_default_config(tmp_path / "out.yaml")
        assert path.exists()
        cfg = load_config(path)
        assert "groceries" in cfg.categories


class TestConfig:
    def test_category_names(self):
        cfg = Config()
        names = cfg.category_names
        assert "groceries" in names
        assert "uncategorized" in names
