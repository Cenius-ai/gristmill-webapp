#!/usr/bin/env bash
# GristMill end-to-end demo.
#
# Seeds a throwaway notebook with real dress settings and grind runs, then
# prints every view the tool offers.  Non-interactive, needs no network, and
# never touches ~/.gristmill.json.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
STORE="$WORKDIR/harvest-2026.json"

say() { printf '\n== %s ==\n' "$1"; }

show() {
    printf '$ gristmill --file %s %s\n' "$STORE" "$*"
    "$PYTHON" gristmill.py --file "$STORE" "$@"
}

say "front door"
"$PYTHON" gristmill.py --help

say "an empty notebook says what to do next"
show dress list

say "record three dress settings on the two stones"
show dress add --stone "French Burr" --pattern "3/4 dress" --gap 12
show dress add --stone "French Burr" --pattern "fine dress" --gap 8
show dress add --stone "Peak" --pattern "cracked dress" --gap 16
show dress list

say "log two grind runs per setting (grain in, flour out)"
show run add --dress 1 --grain-g 1000 --flour-g 718
show run add --dress 1 --grain-g 1000 --flour-g 704
show run add --dress 2 --grain-g 1000 --flour-g 762
show run add --dress 2 --grain-g 1000 --flour-g 754
show run add --dress 3 --grain-g 1000 --flour-g 688
show run add --dress 3 --grain-g 1000 --flour-g 674
show run list

say "which dress is milling best?"
show compare

say "a bad entry is one plain line on stderr and writes nothing"
printf '$ gristmill --file %s run add --dress 1 --grain-g 500 --flour-g 600\n' "$STORE"
set +e
"$PYTHON" gristmill.py --file "$STORE" run add --dress 1 --grain-g 500 --flour-g 600
code=$?
set -e
printf '(exit %s — the notebook was not written)\n' "$code"

say "the store is plain JSON you can read and back up"
printf '$ head -n 12 %s\n' "$STORE"
head -n 12 "$STORE"

say "done"
