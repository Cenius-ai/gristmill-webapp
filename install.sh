#!/usr/bin/env bash
# GristMill install: project-level dependencies only, then exit.
#
# GristMill itself is standard-library only, so the only thing installed here
# is pytest (for the test suite).  No system packages, no services, no server.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 8)' 2>/dev/null; then
    echo "install: Python 3.8 or newer is required (found: $("$PYTHON" -V 2>&1))" >&2
    exit 1
fi

# Keep the packaging tooling current; a stale pip silently skips work.
"$PYTHON" -m pip install --upgrade pip setuptools wheel \
    || echo "install: could not upgrade pip tooling (offline?); continuing" >&2

"$PYTHON" -m pip install -r requirements.txt

# Cheap self-check: fails here, loudly, if the tree is incomplete.
"$PYTHON" -c 'import gristmill; print("gristmill", gristmill.VERSION, "ready (standard library only)")'

cat <<'DONE'

Setup complete. GristMill needs no server and no configuration:
  python3 gristmill.py --help
  bash demo.sh
  python3 -m pytest -q
DONE
