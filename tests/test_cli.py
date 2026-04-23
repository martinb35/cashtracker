"""CLI integration tests."""

from pathlib import Path

from click.testing import CliRunner

from cashtracker.cli import main


class TestParseCommand:
    def test_parse_csv(self, tmp_path: Path):
        csv_file = tmp_path / "statement.csv"
        csv_file.write_text(
            "Date,Description,Amount\n"
            "01/15/2024,WHOLE FOODS MARKET,-45.67\n"
            "01/16/2024,NETFLIX.COM,-15.99\n"
        )
        runner = CliRunner()
        result = runner.invoke(main, ["parse", str(csv_file), "--no-ai"])
        assert result.exit_code == 0
        assert "WHOLE FOODS" in result.output
        assert "groceries" in result.output

    def test_parse_csv_to_file(self, tmp_path: Path):
        csv_file = tmp_path / "statement.csv"
        csv_file.write_text(
            "Date,Description,Amount\n"
            "01/15/2024,STARBUCKS,-5.50\n"
        )
        out_file = tmp_path / "output.csv"
        runner = CliRunner()
        result = runner.invoke(main, ["parse", str(csv_file), "--no-ai", "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "dining" in content

    def test_parse_nonexistent_file(self):
        runner = CliRunner()
        result = runner.invoke(main, ["parse", "nonexistent.csv"])
        assert result.exit_code != 0

    def test_parse_unsupported_format(self, tmp_path: Path):
        txt_file = tmp_path / "statement.txt"
        txt_file.write_text("not a csv")
        runner = CliRunner()
        result = runner.invoke(main, ["parse", str(txt_file)])
        assert result.exit_code != 0
        assert "Unsupported" in result.output

    def test_parse_interactive_no_ai(self, tmp_path: Path):
        csv_file = tmp_path / "statement.csv"
        csv_file.write_text(
            "Date,Description,Amount\n"
            "01/15/2024,MYSTERIOUS PLACE,-20.00\n"
        )
        config_path = tmp_path / "categories.yaml"
        runner = CliRunner()
        # Mock _getch to return '1' (first category = groceries)
        from unittest.mock import patch
        with patch("cashtracker.cli._getch", return_value="1"):
            result = runner.invoke(
                main,
                ["parse", str(csv_file), "--no-ai", "-i", "-c", str(config_path)],
            )
        assert result.exit_code == 0
        assert "Learned 1 new keyword" in result.output
        # Verify keyword was saved
        assert config_path.exists()
        from cashtracker.config import load_config
        cfg = load_config(config_path)
        assert "mysterious place" in cfg.categories["groceries"]


class TestConfigCommands:
    def test_config_init(self, tmp_path: Path):
        runner = CliRunner()
        config_path = tmp_path / "categories.yaml"
        result = runner.invoke(main, ["config", "init", "-p", str(config_path)])
        assert result.exit_code == 0
        assert config_path.exists()

    def test_config_show(self, tmp_path: Path):
        runner = CliRunner()
        # First create a config
        config_path = tmp_path / "categories.yaml"
        runner.invoke(main, ["config", "init", "-p", str(config_path)])
        # Then show it
        result = runner.invoke(main, ["config", "show", "-p", str(config_path)])
        assert result.exit_code == 0
        assert "groceries" in result.output
        assert "Ollama model" in result.output

    def test_config_show_defaults(self, tmp_path: Path):
        runner = CliRunner()
        # Show with no config file — should use defaults
        result = runner.invoke(main, ["config", "show", "-p", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 0
        assert "groceries" in result.output
