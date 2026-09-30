"""First-run behaviour: the messages a new user meets, and the README's own commands.

Exit codes and the output contract are pinned by test_cli.py / test_robustness.py;
this file pins the words around them.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from asset_provenance_toolkit import _atomic
from asset_provenance_toolkit.cli import main

ROOT = Path(__file__).resolve().parent.parent


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["aprov", *argv])
    main()


def _fails(monkeypatch, capsys, argv, code):
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, argv)
    assert exc.value.code == code
    return capsys.readouterr()


# --- a directory is not an asset -------------------------------------------------


@pytest.mark.parametrize("command", ["embed", "extract", "strip", "verify"])
def test_a_directory_is_refused_and_no_sidecar_is_written(monkeypatch, capsys, tmp_path: Path, command):
    folder = tmp_path / "renders"
    folder.mkdir()
    argv = [command, str(folder)]
    if command == "embed":
        argv += ["--capability", "c", "--provider", "p"]
    out = _fails(monkeypatch, capsys, argv, 1)
    assert "is a directory" in out.err + out.out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["renders"]


# --- usage errors say what to type -------------------------------------------------


def test_missing_embed_options_show_the_command_to_type(monkeypatch, capsys, sample_png: Path):
    err = _fails(monkeypatch, capsys, ["embed", str(sample_png)], 2).err
    assert "--capability" in err and "--provider" in err
    assert "hint: " in err and "aprov embed cat.png --capability" in err


def test_no_command_points_to_help(monkeypatch, capsys):
    err = _fails(monkeypatch, capsys, [], 2).err
    assert "hint: " in err and "--help" in err


def test_empty_capability_or_provider_is_a_usage_error(monkeypatch, capsys, sample_png: Path):
    for flag in ("--capability", "--provider"):
        argv = ["embed", str(sample_png), "--capability", "c", "--provider", "p"]
        argv[argv.index(flag) + 1] = "  "
        assert "must not be empty" in _fails(monkeypatch, capsys, argv, 2).err


@pytest.mark.parametrize("command", ["embed", "extract", "verify", "strip", "from-job"])
def test_every_subcommand_help_has_an_example_and_documents_its_arguments(monkeypatch, capsys, command):
    text = _fails(monkeypatch, capsys, [command, "--help"], 0).out  # argparse exits 0 after --help
    assert "example:" in text and f"aprov {command}" in text
    # no bare positional / option without a description line
    assert re.search(r"^\s+file\s{2,}\S", text, re.M)


def test_top_level_help_lists_exit_codes(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["--help"])
    text = capsys.readouterr().out
    assert "exit codes:" in text and "not proof of origin" in text


def test_bad_params_json_says_how_to_quote_it(monkeypatch, capsys, sample_png: Path):
    err = _fails(
        monkeypatch, capsys, ["embed", str(sample_png), "--capability", "c", "--provider", "p", "--params", "{bad"], 1
    ).err
    assert "must be valid JSON" in err and "hint: quote it" in err


# --- from-job -------------------------------------------------------------------


def test_from_job_url_without_a_scheme_is_refused_before_any_request(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.cli as cli_module

    def boom(*a, **k):
        raise AssertionError("must not reach the network")

    monkeypatch.setattr(cli_module, "fetch_job_record", boom)
    err = _fails(
        monkeypatch, capsys, ["from-job", str(sample_png), "--gateway-url", "localhost:9", "--job-id", "j"], 1
    ).err
    assert "must start with http:// or https://" in err


# --- sidecar --------------------------------------------------------------------


def test_sidecar_embed_names_the_sidecar_file(monkeypatch, capsys, sample_non_png: Path):
    _run(monkeypatch, ["embed", str(sample_non_png), "--capability", "c", "--provider", "p"])
    out = capsys.readouterr().out
    assert "sidecar backend" in out and f"{sample_non_png}.provenance.json" in out


def test_a_broken_sidecar_error_names_the_sidecar(monkeypatch, capsys, sample_non_png: Path):
    sidecar = Path(str(sample_non_png) + ".provenance.json")
    sidecar.write_text("{oops", encoding="utf-8")
    err = _fails(monkeypatch, capsys, ["extract", str(sample_non_png)], 1).err
    assert err.startswith("error: ") and sidecar.name in err


# --- a failed write leaves nothing behind -----------------------------------------


def test_failed_replace_of_a_read_only_file_leaves_no_temp_file(monkeypatch, tmp_path: Path):
    """On Windows the temp file inherits the read-only attribute from the asset
    and could not be unlinked, so every failed write left `.name.xxxx.aprov-tmp`."""
    target = tmp_path / "locked.png"
    target.write_bytes(b"original")
    os.chmod(target, stat.S_IREAD)

    def refuse(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(_atomic.os, "replace", refuse)
    try:
        with pytest.raises(PermissionError):
            _atomic.write_atomic(target, b"new bytes")
    finally:
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["locked.png"]
    assert target.read_bytes() == b"original"


def test_permission_denied_is_reported_in_words(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.cli as cli_module

    def deny(path, provenance):
        raise PermissionError(13, "Access is denied", "C:/tmp/.x.aprov-tmp")

    monkeypatch.setattr(cli_module, "embed", deny)
    err = _fails(monkeypatch, capsys, ["embed", str(sample_png), "--capability", "c", "--provider", "p"], 1).err
    assert "permission denied" in err and "aprov-tmp" not in err


# --- README commands ------------------------------------------------------------


def _readme_commands() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        block = block.replace("\\\n", " ")
        for line in block.splitlines():
            line = line.strip()
            match = re.match(r"(?:uv run )?aprov (embed|extract|verify|strip|from-job)\b(.*)", line)
            if match:
                commands.append(line)
    return commands


def test_readme_shows_aprov_commands():
    assert len(_readme_commands()) >= 8


@pytest.mark.parametrize("line", _readme_commands())
def test_readme_command_uses_only_real_subcommands_and_flags(monkeypatch, capsys, line):
    match = re.match(r"(?:uv run )?aprov (\S+)(.*)", line)
    sub, rest = match.group(1), match.group(2)
    with pytest.raises(SystemExit):
        _run(monkeypatch, [sub, "--help"])
    helptext = capsys.readouterr().out
    for flag in re.findall(r"(?<!\S)(--[a-z][a-z-]*)", rest):
        assert flag in helptext, f"{flag} is in the README but not in `aprov {sub} --help`"
