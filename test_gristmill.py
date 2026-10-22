"""End-to-end tests for the GristMill command line tool.

Every test drives the real CLI as a subprocess with an isolated HOME so the
default notebook (~/.gristmill.json) never touches the machine running the
suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "gristmill.py"
sys.path.insert(0, str(ROOT))

EMPTY_DRESSES = (
    "No dress settings yet — add one with: gristmill dress add "
    "--stone <name> --pattern <name> --gap <mil>"
)
EMPTY_RUNS = (
    "No grind runs yet — log one with: gristmill run add "
    "--dress <id> --grain-g <g> --flour-g <g>"
)
EMPTY_COMPARE = (
    "No grind runs to compare yet — log a run with: gristmill run add "
    "--dress <id> --grain-g <g> --flour-g <g>"
)


def run_cli(home: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("NO_COLOR", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or home),
        timeout=60,
    )


def table_rows(stdout: str) -> list[list[str]]:
    """Data rows of a rendered table, minus the header and the rule line."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    return [line.split() for line in lines[2:]]


def header_line(stdout: str) -> str:
    return " ".join(stdout.splitlines()[0].split())


def assert_single_stderr_line(result: subprocess.CompletedProcess) -> None:
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.endswith("\n")
    assert result.stderr.count("\n") == 1, result.stderr


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    directory = tmp_path / "home"
    directory.mkdir()
    return directory


@pytest.fixture()
def store(home: Path) -> Path:
    return home / ".gristmill.json"


# --- F1: dress settings registry --------------------------------------------


def test_dress_add_writes_record_and_creates_store(home: Path, store: Path) -> None:
    result = run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")

    assert result.returncode == 0
    assert result.stdout.strip() == "Added dress 1"
    assert result.stderr == ""
    assert store.exists()
    document = json.loads(store.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert len(document["dresses"]) == 1
    dress = document["dresses"][0]
    assert dress["id"] == 1
    assert dress["stone"] == "Peak"
    assert dress["pattern"] == "3/4 dress"
    assert dress["gap_mil"] == 12


def test_dress_list_empty_prints_guidance_and_exits_zero(home: Path) -> None:
    result = run_cli(home, "dress", "list")

    assert result.returncode == 0
    assert result.stdout.strip() == EMPTY_DRESSES
    assert result.stderr == ""


def test_dress_list_prints_header_and_rows(home: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")
    run_cli(home, "dress", "add", "--stone", "Blue", "--pattern", "fine dress", "--gap", "8")

    result = run_cli(home, "dress", "list")

    assert result.returncode == 0
    assert header_line(result.stdout) == "ID STONE PATTERN GAP(mil)"
    assert table_rows(result.stdout) == [
        ["1", "Peak", "3/4", "dress", "12"],
        ["2", "Blue", "fine", "dress", "8"],
    ]


@pytest.mark.parametrize("gap", ["0", "-4", "abc", "12.5"])
def test_dress_add_rejects_bad_gap_without_writing(home: Path, store: Path, gap: str) -> None:
    result = run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", gap)

    assert_single_stderr_line(result)
    assert result.returncode == 2
    assert "gap must be a positive whole number of thousandths of an inch" in result.stderr
    assert not store.exists()


def test_dress_add_requires_every_flag(home: Path, store: Path) -> None:
    result = run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine")

    assert_single_stderr_line(result)
    assert result.returncode == 2
    assert "--gap" in result.stderr
    assert not store.exists()


# --- F4: store path and --file override --------------------------------------


def test_file_override_keeps_notebooks_separate(home: Path, store: Path, tmp_path: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")
    default_before = store.read_bytes()
    alt = tmp_path / "gm" / "alt.json"

    added = run_cli(home, "--file", str(alt), "dress", "add", "--stone", "Peak", "--pattern", "fine dress", "--gap", "8")
    assert added.returncode == 0
    assert added.stdout.strip() == "Added dress 1"
    assert store.read_bytes() == default_before
    assert json.loads(alt.read_text(encoding="utf-8"))["dresses"][0]["pattern"] == "fine dress"

    listed = run_cli(home, "--file", str(alt), "dress", "list")
    assert listed.returncode == 0
    assert table_rows(listed.stdout) == [["1", "Peak", "fine", "dress", "8"]]


def test_file_option_also_accepted_after_subcommand(home: Path, tmp_path: Path) -> None:
    alt = tmp_path / "after.json"
    result = run_cli(home, "dress", "add", "--file", str(alt), "--stone", "Peak", "--pattern", "fine", "--gap", "8")

    assert result.returncode == 0
    assert alt.exists()


def test_write_leaves_no_temp_files_behind(home: Path, store: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", "8")

    leftovers = [entry.name for entry in store.parent.iterdir() if entry.name.startswith(".gristmill-")]
    assert leftovers == []
    json.loads(store.read_text(encoding="utf-8"))  # still a whole document


# --- F2: grind runs with stored yield ---------------------------------------


def test_run_add_stores_yield_rounded_to_one_decimal(home: Path, store: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")

    result = run_cli(home, "run", "add", "--dress", "1", "--grain-g", "1000", "--flour-g", "720")
    assert result.returncode == 0
    assert result.stdout.strip() == "Added run 1 with yield 72.0%"

    run = json.loads(store.read_text(encoding="utf-8"))["runs"][0]
    assert run["id"] == 1
    assert run["dress_id"] == 1
    assert run["grain_g"] == 1000
    assert run["flour_g"] == 720
    assert run["yield_pct"] == 72.0

    rounded = run_cli(home, "run", "add", "--dress", "1", "--grain-g", "300", "--flour-g", "200")
    assert rounded.stdout.strip() == "Added run 2 with yield 66.7%"
    assert json.loads(store.read_text(encoding="utf-8"))["runs"][1]["yield_pct"] == 66.7


def test_run_list_empty_prints_guidance_and_exits_zero(home: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", "8")

    result = run_cli(home, "run", "list")

    assert result.returncode == 0
    assert result.stdout.strip() == EMPTY_RUNS
    assert result.stderr == ""


def test_run_list_prints_header_and_rows(home: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")
    run_cli(home, "run", "add", "--dress", "1", "--grain-g", "1000", "--flour-g", "720")

    result = run_cli(home, "run", "list")

    assert result.returncode == 0
    assert header_line(result.stdout) == "ID DRESS GRAIN(g) FLOUR(g) YIELD%"
    assert table_rows(result.stdout) == [["1", "1", "1000", "720", "72.0%"]]


def test_run_add_rejects_unknown_dress_without_writing(home: Path, store: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", "8")
    before = store.read_bytes()

    result = run_cli(home, "run", "add", "--dress", "99", "--grain-g", "1000", "--flour-g", "700")

    assert_single_stderr_line(result)
    assert result.returncode == 2
    assert "no dress setting with id 99" in result.stderr
    assert store.read_bytes() == before


def test_run_add_rejects_flour_over_grain_without_writing(home: Path, store: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", "8")
    before = store.read_bytes()

    result = run_cli(home, "run", "add", "--dress", "1", "--grain-g", "500", "--flour-g", "600")

    assert_single_stderr_line(result)
    assert result.returncode == 2
    assert "flour cannot exceed grain" in result.stderr
    assert store.read_bytes() == before


def test_run_add_rejects_non_positive_grain(home: Path, store: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", "8")

    result = run_cli(home, "run", "add", "--dress", "1", "--grain-g", "0", "--flour-g", "0")

    assert_single_stderr_line(result)
    assert result.returncode == 2
    assert "grain weight must be greater than zero" in result.stderr


# --- F3: yield comparison ----------------------------------------------------


def test_compare_ranks_dresses_by_mean_yield(home: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine dress", "--gap", "8")
    run_cli(home, "run", "add", "--dress", "1", "--grain-g", "1000", "--flour-g", "720")
    run_cli(home, "run", "add", "--dress", "1", "--grain-g", "1000", "--flour-g", "680")
    run_cli(home, "run", "add", "--dress", "2", "--grain-g", "1000", "--flour-g", "800")

    result = run_cli(home, "compare")

    assert result.returncode == 0
    assert header_line(result.stdout) == "RANK DRESS STONE PATTERN GAP(mil) RUNS MEAN YIELD%"
    rows = table_rows(result.stdout)
    assert rows[0] == ["1", "2", "Peak", "fine", "dress", "8", "1", "80.0%"]
    assert rows[1] == ["2", "1", "Peak", "3/4", "dress", "12", "2", "70.0%"]


def test_compare_ties_break_on_lower_dress_id_and_repeat_identically(home: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "3/4 dress", "--gap", "12")
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine dress", "--gap", "8")
    run_cli(home, "run", "add", "--dress", "1", "--grain-g", "1000", "--flour-g", "750")
    run_cli(home, "run", "add", "--dress", "2", "--grain-g", "1000", "--flour-g", "750")

    first = run_cli(home, "compare")
    second = run_cli(home, "compare")

    assert first.returncode == 0
    assert first.stdout == second.stdout
    rows = table_rows(first.stdout)
    assert rows[0][:2] == ["1", "1"]
    assert rows[1][:2] == ["2", "2"]


def test_compare_empty_prints_guidance_and_exits_zero(home: Path) -> None:
    run_cli(home, "dress", "add", "--stone", "Peak", "--pattern", "fine", "--gap", "8")

    result = run_cli(home, "compare")

    assert result.returncode == 0
    assert result.stdout.strip() == EMPTY_COMPARE
    assert result.stderr == ""


# --- Error contract ----------------------------------------------------------


def test_corrupt_store_is_one_line_exit_3_and_left_untouched(home: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"not json at all")

    for command in (["dress", "list"], ["run", "list"], ["compare"]):
        result = run_cli(home, "--file", str(bad), *command)
        assert_single_stderr_line(result)
        assert result.returncode == 3
        assert str(bad) in result.stderr
        assert bad.read_bytes() == b"not json at all"


def test_unwritable_store_reports_one_line(home: Path, tmp_path: Path) -> None:
    directory = tmp_path / "as-directory.json"
    directory.mkdir()

    result = run_cli(home, "--file", str(directory), "dress", "list")

    assert_single_stderr_line(result)
    assert result.returncode == 3


def test_unknown_command_is_one_line_exit_2(home: Path) -> None:
    result = run_cli(home, "grind")

    assert_single_stderr_line(result)
    assert result.returncode == 2


# --- Help coverage -----------------------------------------------------------


def test_help_lists_every_command_and_the_file_option(home: Path) -> None:
    top = run_cli(home, "--help")
    assert top.returncode == 0
    for token in ("dress", "run", "compare", "--file"):
        assert token in top.stdout

    dress_help = run_cli(home, "dress", "--help")
    assert dress_help.returncode == 0
    assert "add" in dress_help.stdout and "list" in dress_help.stdout
    assert "--file" in dress_help.stdout

    run_help = run_cli(home, "run", "--help")
    assert run_help.returncode == 0
    assert "add" in run_help.stdout and "list" in run_help.stdout
    assert "--file" in run_help.stdout

    for command in ("dress add", "dress list", "run add", "run list", "compare"):
        leaf = run_cli(home, *command.split(), "--help")
        assert leaf.returncode == 0, command
        assert "--file" in leaf.stdout, command


def test_version_flag(home: Path) -> None:
    result = run_cli(home, "--version")
    assert result.returncode == 0
    assert result.stdout.strip().startswith("gristmill ")


def test_bare_invocation_prints_help_and_exits_zero(home: Path) -> None:
    result = run_cli(home)

    assert result.returncode == 0
    assert "usage: gristmill" in result.stdout
