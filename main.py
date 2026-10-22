#!/usr/bin/env python3
"""Entry point shim so GristMill can be run as ``python3 main.py``.

The product itself is the single file ``gristmill.py``; this shim only exists
so the tool is reachable from the conventional module name as well as by its
own script path.  Both forms are identical:

    python3 main.py compare
    python3 gristmill.py compare
"""

from gristmill import main

if __name__ == "__main__":
    raise SystemExit(main())
