# Installing GristMill

GristMill is one Python file that uses only the standard library. There is no
package to build, no service to start and no configuration to write.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.8 or newer | `python3 -V` should print 3.8 or higher. Nothing else is installed system-wide, and GristMill never installs system packages. |
| `pytest` (optional) | Only for running the test suite; the tool itself runs without it. |

## Step 1 — get the files

Copy the project directory (or just `gristmill.py`) onto the machine. No
network access is needed at any point after that.

## Step 2 — install the test runner (optional)

```bash
bash install.sh
```

`install.sh` upgrades `pip`/`setuptools`/`wheel`, installs the single project
dependency from `requirements.txt` (`pytest`, test-only), runs an import
self-check and **exits**. It installs nothing system-wide, starts no service
and never starts a long-running process.

If you would rather do it by hand:

```bash
python3 -m pip install -r requirements.txt
python3 -c 'import gristmill; print(gristmill.VERSION)'
```

## Step 3 — verify

```bash
python3 gristmill.py --help
bash demo.sh
```

`demo.sh` seeds a throwaway notebook in a temporary directory, prints every
view, and leaves `~/.gristmill.json` untouched.

## Step 4 — run it

GristMill is a command line tool; there is no server and nothing binds a port.

```bash
python3 gristmill.py dress add --stone "French Burr" --pattern "3/4 dress" --gap 12
python3 gristmill.py run add --dress 1 --grain-g 1000 --flour-g 718
python3 gristmill.py compare
```

`python3 main.py …` is an equivalent entry point. If you want the bare
`gristmill` command on your `PATH`, add an alias or a small wrapper:

```bash
alias gristmill='python3 /path/to/gristmill.py'
```

## Step 5 — run the tests

```bash
python3 -m pytest -q
```

The suite uses no network and no external services; it creates its own
temporary notebooks under a temporary `HOME`.

## Data and backups

The notebook lives at `~/.gristmill.json` (or wherever `--file` points). It is
indented JSON written atomically; copy it anywhere to back it up. Delete it to
start a fresh notebook — there is nothing to migrate and no schema upgrade
path, because this is the first schema version.
