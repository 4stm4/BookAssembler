"""Benchmark CLI and its regression exit code (RFC 0009 §4, §5.3)."""

import json

from src.benchmark.runner import main


def _sample(corpus_dir, name: str, expected_text: str, actual_text: str) -> None:
    sample = corpus_dir / name
    expected = sample / "expected"
    expected.mkdir(parents=True)
    (sample / "input.md").write_text(actual_text, encoding="utf-8")
    (expected / "expected_text.txt").write_text(expected_text, encoding="utf-8")


def test_matching_sample_passes(tmp_path, capsys) -> None:
    corpus = tmp_path / "corpus"
    _sample(corpus, "clean", "# Title\n\nMOV R0, R1", "# Title\n\nMOV R0, R1")

    exit_code = main(["--corpus-dir", str(corpus)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)[0]["document_name"] == "clean"


def test_strict_flag_turns_a_regression_into_a_nonzero_exit(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    _sample(corpus, "drifted", "completely different reference text here", "# X\n\nnothing alike")

    assert main(["--corpus-dir", str(corpus), "--strict-regression-check"]) == 1
    assert main(["--corpus-dir", str(corpus)]) == 0


def test_report_is_written_to_disk(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    _sample(corpus, "clean", "# Title", "# Title")
    report = tmp_path / "report.json"

    main(["--corpus-dir", str(corpus), "--report-out", str(report)])

    assert json.loads(report.read_text())[0]["document_name"] == "clean"


def test_empty_corpus_is_an_error(tmp_path) -> None:
    assert main(["--corpus-dir", str(tmp_path / "missing")]) == 1
