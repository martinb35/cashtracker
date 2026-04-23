"""Tests for CSV file reader."""

from cashtracker.readers.csv_reader import read_csv


class TestReadCSV:
    def test_basic_csv(self, tmp_csv):
        path = tmp_csv([
            {"Date": "01/15/2024", "Description": "GROCERY STORE", "Amount": "-45.67"},
            {"Date": "01/16/2024", "Description": "NETFLIX", "Amount": "-15.99"},
        ])
        rows = read_csv(path)
        assert len(rows) == 2
        assert rows[0]["Date"] == "01/15/2024"
        assert rows[0]["Description"] == "GROCERY STORE"

    def test_semicolon_delimiter(self, tmp_path):
        path = tmp_path / "test.csv"
        path.write_text("Date;Description;Amount\n01/15/2024;STORE;-10.00\n", encoding="utf-8")
        rows = read_csv(path)
        assert len(rows) == 1
        assert rows[0]["Date"] == "01/15/2024"

    def test_whitespace_stripped(self, tmp_csv):
        path = tmp_csv([
            {"Date": " 01/15/2024 ", "Description": " STORE ", "Amount": " -10 "},
        ])
        rows = read_csv(path)
        assert rows[0]["Date"] == "01/15/2024"
        assert rows[0]["Description"] == "STORE"
        assert rows[0]["Amount"] == "-10"

    def test_empty_csv(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("Date,Description,Amount\n", encoding="utf-8")
        rows = read_csv(path)
        assert rows == []

    def test_utf8_bom(self, tmp_path):
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbfDate,Amount\n01/01/2024,100\n")
        rows = read_csv(path)
        assert len(rows) == 1
        assert "Date" in rows[0]
