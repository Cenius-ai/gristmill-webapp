#!/usr/bin/env python3
"""GristMill - burr stone dress settings, grind runs and flour yield.

A single-file, standard-library-only command line tool for a small-mill
miller.  Every record lives in one plain JSON notebook (by default
``~/.gristmill.json``, overridable with the global ``--file`` option) that the
operator can read, copy or back up by hand.

    gristmill dress add --stone Peak --pattern "3/4 dress" --gap 12
    gristmill run add --dress 1 --grain-g 1000 --flour-g 720
    gristmill compare

Design direction (committed, see README "Design tokens"): calm-precise,
terminal dark, monospace, compact; aligned columns with box-drawing
separators; a single accent (oklch(0.58 0.12 153) == #368e57) used only for
primary status and never as the sole signal.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

PROG = "gristmill"
VERSION = "1.0.0"
SCHEMA_VERSION = 1
DEFAULT_STORE = os.path.join("~", ".gristmill.json")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DATA = 3

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

GAP_RULE = "gap must be a positive whole number of thousandths of an inch"

# --- Committed design tokens -------------------------------------------------
# Terminal dark neutral ramp built around the project accent.  Values are hex
# so they can drive ANSI truecolor here and any non-CSS surface elsewhere;
# the CSS/OKLCH form is recorded for documentation and future surfaces.
THEME = {
    "bg": "#0b0f0d",
    "surface": "#121815",
    "text": "#d5dbd7",
    "muted": "#7c8a80",
    "accent": "#368e57",  # oklch(0.58 0.12 153)
}
THEME_OKLCH_ACCENT = "oklch(0.58 0.12 153)"

# Column layout: numbers right-aligned, text left-aligned, two-space gutters,
# one box-drawing rule under the header row.
COLUMN_GUTTER = "  "
RULE_CHAR = "─"


class GristMillError(Exception):
    """A failure the operator should read as one plain line on stderr."""

    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# --- Terminal styling --------------------------------------------------------


def _truecolor(hex_color: str) -> str:
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    return "\x1b[38;2;{};{};{}m".format(red, green, blue)


class Palette:
    """Accent for primary status, muted for chrome; silent when not a TTY."""

    RESET = "\x1b[0m"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._accent = _truecolor(THEME["accent"]) if enabled else ""
        self._muted = _truecolor(THEME["muted"]) if enabled else ""
        self._bold = "\x1b[1m" if enabled else ""

    def accent(self, text: str) -> str:
        return self._accent + text + self.RESET if self.enabled else text

    def muted(self, text: str) -> str:
        return self._muted + text + self.RESET if self.enabled else text

    def heading(self, text: str) -> str:
        return self._bold + text + self.RESET if self.enabled else text


def build_palette(stream: Any = None) -> Palette:
    stream = stream if stream is not None else sys.stdout
    if os.environ.get("NO_COLOR") is not None:
        return Palette(False)
    if os.environ.get("TERM") == "dumb":
        return Palette(False)
    try:
        is_tty = bool(stream.isatty())
    except (AttributeError, ValueError):
        is_tty = False
    return Palette(is_tty)


# --- Small formatting helpers ------------------------------------------------


def utc_now() -> str:
    stamp = datetime.now(timezone.utc).replace(microsecond=0)
    return stamp.isoformat().replace("+00:00", "Z")


def fmt_weight(value: float) -> str:
    """Grams as the operator typed them: 1000 -> '1000', 720.5 -> '720.5'."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    text = "{:.3f}".format(number).rstrip("0").rstrip(".")
    return text or "0"


def fmt_yield(value: float) -> str:
    return "{:.1f}%".format(float(value))


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    right_aligned: Sequence[int] = (),
    palette: Optional[Palette] = None,
) -> List[str]:
    """Aligned monospace columns with one box-drawing rule under the header."""
    palette = palette or Palette(False)
    right = set(right_aligned)
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))

    def pad(text: str, index: int) -> str:
        width = widths[index]
        return text.rjust(width) if index in right else text.ljust(width)

    header_line = COLUMN_GUTTER.join(
        pad(header, index) for index, header in enumerate(headers)
    )
    rule_line = COLUMN_GUTTER.join(RULE_CHAR * width for width in widths)
    lines = [palette.heading(header_line), palette.muted(rule_line)]
    for row in rows:
        lines.append(COLUMN_GUTTER.join(pad(cell, index) for index, cell in enumerate(row)))
    return lines


def emit(lines: Sequence[str]) -> None:
    print("\n".join(lines))


# --- Store -------------------------------------------------------------------


def empty_store() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "next_dress_id": 1,
        "next_run_id": 1,
        "dresses": [],
        "runs": [],
    }


def resolve_store_path(file_option: Optional[str]) -> str:
    raw = file_option if file_option else DEFAULT_STORE
    return os.path.abspath(os.path.expanduser(raw))


def _corrupt(path: str, detail: str) -> GristMillError:
    return GristMillError(
        "data file {} is unreadable as a GristMill store ({}) and was left "
        "untouched".format(path, detail),
        EXIT_DATA,
    )


def _require_int(value: Any, path: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _corrupt(path, "{} is not a whole number".format(field))
    return value


def _require_number(value: Any, path: str, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _corrupt(path, "{} is not a number".format(field))
    number = float(value)
    if not math.isfinite(number):
        raise _corrupt(path, "{} is not a finite number".format(field))
    return number


def _require_text(value: Any, path: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _corrupt(path, "{} is not a non-empty string".format(field))
    return value


def _normalize_dress(entry: Any, path: str) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise _corrupt(path, "a dress setting is not a JSON object")
    return {
        "id": _require_int(entry.get("id"), path, "dress id"),
        "stone": _require_text(entry.get("stone"), path, "dress stone"),
        "pattern": _require_text(entry.get("pattern"), path, "dress pattern"),
        "gap_mil": _require_int(entry.get("gap_mil"), path, "dress gap_mil"),
        "created_at": str(entry.get("created_at") or ""),
    }


def _normalize_run(entry: Any, path: str) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise _corrupt(path, "a grind run is not a JSON object")
    return {
        "id": _require_int(entry.get("id"), path, "run id"),
        "dress_id": _require_int(entry.get("dress_id"), path, "run dress_id"),
        "grain_g": _require_number(entry.get("grain_g"), path, "run grain_g"),
        "flour_g": _require_number(entry.get("flour_g"), path, "run flour_g"),
        "yield_pct": _require_number(entry.get("yield_pct"), path, "run yield_pct"),
        "created_at": str(entry.get("created_at") or ""),
    }


def _next_id(stored: Any, existing: Sequence[int], floor: int = 1) -> int:
    candidate = floor
    if isinstance(stored, int) and not isinstance(stored, bool) and stored >= floor:
        candidate = stored
    highest = max(existing) + 1 if existing else floor
    return max(candidate, highest)


def normalize_store(document: Any, path: str) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise _corrupt(path, "the top level is not a JSON object")
    raw_dresses = document.get("dresses", [])
    raw_runs = document.get("runs", [])
    if not isinstance(raw_dresses, list):
        raise _corrupt(path, "'dresses' is not a list")
    if not isinstance(raw_runs, list):
        raise _corrupt(path, "'runs' is not a list")
    dresses = [_normalize_dress(entry, path) for entry in raw_dresses]
    runs = [_normalize_run(entry, path) for entry in raw_runs]
    return {
        "schema_version": SCHEMA_VERSION,
        "next_dress_id": _next_id(
            document.get("next_dress_id"), [dress["id"] for dress in dresses]
        ),
        "next_run_id": _next_id(document.get("next_run_id"), [run["id"] for run in runs]),
        "dresses": dresses,
        "runs": runs,
    }


def load_store(path: str) -> Dict[str, Any]:
    """Read the notebook; a missing file is an empty notebook, not an error."""
    if not os.path.exists(path):
        return empty_store()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise GristMillError(
            "cannot read data file {} ({})".format(path, reason), EXIT_DATA
        )
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise GristMillError(
            "data file {} is not valid JSON and was left untouched".format(path),
            EXIT_DATA,
        )
    return normalize_store(document, path)


def write_store(path: str, store: Dict[str, Any]) -> None:
    """Write atomically: temp file in the same directory, fsync, then rename."""
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise GristMillError(
            "cannot create directory {} ({})".format(directory, reason), EXIT_DATA
        )
    payload = json.dumps(store, indent=2, ensure_ascii=False) + "\n"
    descriptor = -1
    temp_path = ""
    try:
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".gristmill-", suffix=".tmp", dir=directory
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = ""
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise GristMillError(
            "cannot write data file {} ({})".format(path, reason), EXIT_DATA
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


# --- Argument validation -----------------------------------------------------


def parse_gap(raw: Optional[str]) -> int:
    text = (raw or "").strip()
    try:
        value = int(text)
    except ValueError:
        raise GristMillError(
            "{} (got '{}')".format(GAP_RULE, text), EXIT_USAGE
        )
    if value <= 0:
        raise GristMillError("{} (got {})".format(GAP_RULE, value), EXIT_USAGE)
    return value


def parse_int_arg(raw: Optional[str], label: str) -> int:
    text = (raw or "").strip()
    try:
        return int(text)
    except ValueError:
        raise GristMillError(
            "{} must be a whole number (got '{}')".format(label, text), EXIT_USAGE
        )


def parse_grams(raw: Optional[str], label: str) -> float:
    text = (raw or "").strip()
    try:
        value = float(text)
    except ValueError:
        raise GristMillError(
            "{} must be a number of grams (got '{}')".format(label, text), EXIT_USAGE
        )
    if not math.isfinite(value):
        raise GristMillError(
            "{} must be a number of grams (got '{}')".format(label, text), EXIT_USAGE
        )
    return value


# --- Commands ----------------------------------------------------------------


def cmd_dress_add(
    store: Dict[str, Any], path: str, args: argparse.Namespace, palette: Palette
) -> int:
    stone = (args.stone or "").strip()
    pattern = (args.pattern or "").strip()
    if not stone:
        raise GristMillError("stone name cannot be empty", EXIT_USAGE)
    if not pattern:
        raise GristMillError("dress pattern cannot be empty", EXIT_USAGE)
    gap_mil = parse_gap(args.gap)

    dress = {
        "id": store["next_dress_id"],
        "stone": stone,
        "pattern": pattern,
        "gap_mil": gap_mil,
        "created_at": utc_now(),
    }
    store["dresses"].append(dress)
    store["next_dress_id"] = dress["id"] + 1
    write_store(path, store)
    print(palette.accent("Added dress {}".format(dress["id"])))
    return EXIT_OK


def cmd_dress_list(store: Dict[str, Any], palette: Palette) -> int:
    dresses = sorted(store["dresses"], key=lambda dress: dress["id"])
    if not dresses:
        print(EMPTY_DRESSES)
        return EXIT_OK
    rows = [
        [str(dress["id"]), dress["stone"], dress["pattern"], str(dress["gap_mil"])]
        for dress in dresses
    ]
    emit(render_table(["ID", "STONE", "PATTERN", "GAP(mil)"], rows, [0, 3], palette))
    return EXIT_OK


def cmd_run_add(
    store: Dict[str, Any], path: str, args: argparse.Namespace, palette: Palette
) -> int:
    dress_id = parse_int_arg(args.dress, "dress id")
    grain_g = parse_grams(args.grain_g, "grain weight")
    flour_g = parse_grams(args.flour_g, "flour weight")
    if grain_g <= 0:
        raise GristMillError(
            "grain weight must be greater than zero (got {})".format(fmt_weight(grain_g)),
            EXIT_USAGE,
        )
    if flour_g < 0:
        raise GristMillError(
            "flour weight cannot be negative (got {})".format(fmt_weight(flour_g)),
            EXIT_USAGE,
        )
    if flour_g > grain_g:
        raise GristMillError(
            "flour cannot exceed grain (flour {} g, grain {} g)".format(
                fmt_weight(flour_g), fmt_weight(grain_g)
            ),
            EXIT_USAGE,
        )
    known = {dress["id"] for dress in store["dresses"]}
    if dress_id not in known:
        raise GristMillError(
            "no dress setting with id {} — run 'gristmill dress list' to see the "
            "settings you have".format(dress_id),
            EXIT_USAGE,
        )

    run = {
        "id": store["next_run_id"],
        "dress_id": dress_id,
        "grain_g": float(grain_g),
        "flour_g": float(flour_g),
        "yield_pct": round(flour_g / grain_g * 100.0, 1),
        "created_at": utc_now(),
    }
    store["runs"].append(run)
    store["next_run_id"] = run["id"] + 1
    write_store(path, store)
    print(
        palette.accent(
            "Added run {} with yield {}".format(run["id"], fmt_yield(run["yield_pct"]))
        )
    )
    return EXIT_OK


def cmd_run_list(store: Dict[str, Any], palette: Palette) -> int:
    runs = sorted(store["runs"], key=lambda run: run["id"])
    if not runs:
        print(EMPTY_RUNS)
        return EXIT_OK
    rows = [
        [
            str(run["id"]),
            str(run["dress_id"]),
            fmt_weight(run["grain_g"]),
            fmt_weight(run["flour_g"]),
            fmt_yield(run["yield_pct"]),
        ]
        for run in runs
    ]
    emit(
        render_table(
            ["ID", "DRESS", "GRAIN(g)", "FLOUR(g)", "YIELD%"],
            rows,
            [0, 1, 2, 3, 4],
            palette,
        )
    )
    return EXIT_OK


def cmd_compare(store: Dict[str, Any], palette: Palette) -> int:
    if not store["runs"]:
        print(EMPTY_COMPARE)
        return EXIT_OK
    yields_by_dress: Dict[int, List[float]] = {}
    for run in store["runs"]:
        yields_by_dress.setdefault(run["dress_id"], []).append(run["yield_pct"])
    dresses_by_id = {dress["id"]: dress for dress in store["dresses"]}

    standings = []
    for dress_id, yields in yields_by_dress.items():
        mean_yield = round(sum(yields) / len(yields), 1)
        standings.append((dress_id, mean_yield, len(yields)))
    # Highest mean yield first; ties fall back to the lower dress id so two
    # identical invocations always print the same ranking.
    standings.sort(key=lambda item: (-item[1], item[0]))

    rows = []
    for rank, (dress_id, mean_yield, run_count) in enumerate(standings, start=1):
        dress = dresses_by_id.get(dress_id)
        stone = dress["stone"] if dress else "?"
        pattern = dress["pattern"] if dress else "?"
        gap = str(dress["gap_mil"]) if dress else "?"
        rows.append(
            [str(rank), str(dress_id), stone, pattern, gap, str(run_count), fmt_yield(mean_yield)]
        )
    emit(
        render_table(
            ["RANK", "DRESS", "STONE", "PATTERN", "GAP(mil)", "RUNS", "MEAN YIELD%"],
            rows,
            [0, 1, 4, 5, 6],
            palette,
        )
    )
    return EXIT_OK


# --- Parser ------------------------------------------------------------------


class GristMillParser(argparse.ArgumentParser):
    """argparse, but a usage failure is still exactly one line on stderr."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.exit(EXIT_USAGE, "{}: {}\n".format(self.prog, message))


def _store_option() -> argparse.ArgumentParser:
    """Shared --file so it can be written before or after a subcommand."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--file",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="path to the JSON notebook (default: ~/.gristmill.json)",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    store_option = _store_option()
    _GROUP_PARSERS.clear()
    parser = GristMillParser(
        prog=PROG,
        description=(
            "Track burr stone dress settings, log grind runs and compare flour "
            "yield across dress settings."
        ),
        epilog=(
            "examples:\n"
            "  gristmill dress add --stone Peak --pattern '3/4 dress' --gap 12\n"
            "  gristmill dress list\n"
            "  gristmill run add --dress 1 --grain-g 1000 --flour-g 720\n"
            "  gristmill run list\n"
            "  gristmill compare\n"
            "  gristmill --file ~/notebooks/spring.json compare\n"
            "\n"
            "records are append-only; every failure prints one line on stderr."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default=None,
        help="path to the JSON notebook (default: ~/.gristmill.json)",
    )
    parser.add_argument(
        "--version", action="version", version="{} {}".format(PROG, VERSION)
    )
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    dress = subcommands.add_parser(
        "dress",
        parents=[store_option],
        help="record and list stone dress settings",
        description="Record and list the stone dress settings runs are ground on.",
    )
    dress_actions = dress.add_subparsers(dest="dress_action", metavar="ACTION")
    dress_add = dress_actions.add_parser(
        "add",
        parents=[store_option],
        help="record a new dress setting",
        description="Record a new dress setting and return its id.",
    )
    dress_add.add_argument("--stone", required=True, metavar="NAME", help="stone name")
    dress_add.add_argument(
        "--pattern", required=True, metavar="NAME", help="dress pattern name"
    )
    dress_add.add_argument(
        "--gap",
        required=True,
        metavar="MIL",
        help="stone gap in whole thousandths of an inch (positive)",
    )
    _GROUP_PARSERS["dress"] = dress
    dress_list = dress_actions.add_parser(
        "list",
        parents=[store_option],
        help="list dress settings ascending by id",
        description="List every dress setting ascending by id.",
    )
    dress_list.set_defaults(dress_action="list")

    run = subcommands.add_parser(
        "run",
        parents=[store_option],
        help="log grind runs and list stored yields",
        description="Log grind runs and list the yield stored with each run.",
    )
    run_actions = run.add_subparsers(dest="run_action", metavar="ACTION")
    run_add = run_actions.add_parser(
        "add",
        parents=[store_option],
        help="log a grind run against a dress setting",
        description=(
            "Log a grind run; yield is flour/grain*100 rounded to one decimal "
            "and stored with the run."
        ),
    )
    run_add.add_argument(
        "--dress", required=True, metavar="ID", help="dress setting id the run used"
    )
    run_add.add_argument(
        "--grain-g", required=True, metavar="G", help="grain weight in grams"
    )
    run_add.add_argument(
        "--flour-g", required=True, metavar="G", help="flour weight in grams"
    )
    _GROUP_PARSERS["run"] = run
    run_list = run_actions.add_parser(
        "list",
        parents=[store_option],
        help="list grind runs ascending by id",
        description="List every grind run with its stored yield, ascending by id.",
    )
    run_list.set_defaults(run_action="list")

    subcommands.add_parser(
        "compare",
        parents=[store_option],
        help="rank dress settings by mean flour yield",
        description=(
            "Group every run by dress setting and rank the settings by mean "
            "yield, highest first; ties go to the lower dress id."
        ),
    )

    return parser


def dispatch(args: argparse.Namespace, palette: Palette) -> int:
    path = resolve_store_path(getattr(args, "file", None))

    if args.command == "dress":
        action = getattr(args, "dress_action", None)
        if action == "add":
            return cmd_dress_add(load_store(path), path, args, palette)
        if action == "list":
            return cmd_dress_list(load_store(path), palette)
        return _print_group_help(args.command)

    if args.command == "run":
        action = getattr(args, "run_action", None)
        if action == "add":
            return cmd_run_add(load_store(path), path, args, palette)
        if action == "list":
            return cmd_run_list(load_store(path), palette)
        return _print_group_help(args.command)

    if args.command == "compare":
        return cmd_compare(load_store(path), palette)

    return _print_group_help(None)


_PARSER: Optional[argparse.ArgumentParser] = None
_GROUP_PARSERS: Dict[str, argparse.ArgumentParser] = {}


def _print_group_help(command: Optional[str]) -> int:
    """Bare invocation is guidance, not an error: print help, exit 0."""
    parser = _PARSER or build_parser()
    chosen = _GROUP_PARSERS.get(command) if command else None
    (chosen or parser).print_help(sys.stdout)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    global _PARSER
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    _PARSER = build_parser()
    args = _PARSER.parse_args(list(argv) if argv is not None else None)
    palette = build_palette(sys.stdout)
    try:
        return dispatch(args, palette)
    except GristMillError as error:
        print("{}: {}".format(PROG, error.message), file=sys.stderr)
        return error.code


if __name__ == "__main__":
    raise SystemExit(main())
