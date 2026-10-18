import json
from pathlib import Path

import pytest

from zotero_shelf import cli, config
from zotero_shelf.errors import ShelfError
from zotero_shelf.library import Library


@pytest.fixture
def connected_cli(tmp_path, monkeypatch, settings, api_transport):
    path = tmp_path / "config.json"
    config.private_json(path, settings)
    transport, _ = api_transport
    monkeypatch.setattr(cli, "Library", lambda settings: Library(settings, transport))
    return ["--config", str(path)]


def test_json_search_with_flags_before_and_after_command(connected_cli, capsys):
    assert cli.main([*connected_cli, "--json", "search", "example", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["key"] == "ABCD1234"
    assert cli.main(["search", "example", *connected_cli, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1


def test_human_search(connected_cli, capsys):
    assert cli.main([*connected_cli, "search", "example"]) == 0
    output = capsys.readouterr().out
    assert "ABCD1234" in output
    assert "example research article" in output


def test_json_errors_never_echo_http_secrets(monkeypatch, capsys):
    def fail(_):
        raise RuntimeError("AUTHORIZATION: VERY-SECRET-TEST-TOKEN")

    monkeypatch.setattr(cli, "execute", fail)
    assert cli.main(["status", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "VERY-SECRET" not in captured.err
    assert json.loads(captured.err)["error"]["exit_code"] == 1


def test_setup_refuses_to_save_unverified_credentials(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.json"
    path.write_text('{"library_id":"123","api_key":"OLD"}', encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "123")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "NEW-SECRET")

    class Rejected:
        def __init__(self, _):
            raise ShelfError("Authentication failed")

    monkeypatch.setattr(cli, "Library", Rejected)
    assert cli.main(["setup", "--config", str(path)]) == 2
    assert json.loads(path.read_text())["api_key"] == "OLD"
    assert "NEW-SECRET" not in capsys.readouterr().err


def test_export_output_does_not_overwrite(connected_cli, tmp_path, capsys):
    path = tmp_path / "references.bib"
    path.write_text("Existing bibliography", encoding="utf-8")
    assert cli.main([*connected_cli, "export", "ABCD1234", "-o", str(path)]) == 2
    assert path.read_text() == "Existing bibliography"
    assert "already exists" in capsys.readouterr().err


def test_nested_webdav_flags_parse():
    args = cli.parser().parse_args(["--json", "webdav", "check", "--key", "ABCD1234"])
    assert args.json and args.key == "ABCD1234"


def test_indexed_text_works_without_webdav(connected_cli, capsys):
    assert cli.main([*connected_cli, "text", "ABCD1234", "--indexed"]) == 0
    assert "Indexed example PDF text" in capsys.readouterr().out


def test_pdf_text_missing_poppler_is_actionable(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    with pytest.raises(ShelfError, match="pdftotext"):
        cli._pdf_text(Path("example.pdf"))


@pytest.mark.parametrize("json_mode", [False, True])
def test_csl_export_prints_an_array_of_citations(connected_cli, capsys, json_mode):
    args = [*connected_cli, "export", "ABCD1234", "--format", "csljson"]
    if json_mode:
        args.append("--json")
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert isinstance(result, list)
    assert result[0]["type"] == "article-journal"


def test_csl_export_saves_an_array_of_citations(connected_cli, tmp_path, capsys):
    output = tmp_path / "citations.json"
    assert (
        cli.main([*connected_cli, "export", "ABCD1234", "--format", "csljson", "-o", str(output)])
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(result, list)
    assert result[0]["type"] == "article-journal"
