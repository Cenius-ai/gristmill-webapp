# Using GristMill

Walkthroughs of what the tool actually does. Run the tool as
`python3 gristmill.py …` (or `python3 main.py …`) from the project directory.

## 1. Set up a dress setting

A dress setting is the stone + dress pattern + gap combination you grind on.
Record it once and point every run at it.

```bash
$ python3 gristmill.py dress add --stone "French Burr" --pattern "3/4 dress" --gap 12
Added dress 1

$ python3 gristmill.py dress add --stone "French Burr" --pattern "fine dress" --gap 8
Added dress 2

$ python3 gristmill.py dress list
ID  STONE        PATTERN     GAP(mil)
──  ───────────  ──────────  ────────
 1  French Burr  3/4 dress         12
 2  French Burr  fine dress         8
```

Gaps are whole thousandths of an inch and must be positive. A zero, negative
or non-integer gap is rejected before anything is written:

```bash
$ python3 gristmill.py dress add --stone Peak --pattern fine --gap 0
gristmill: gap must be a positive whole number of thousandths of an inch (got 0)
$ echo $?
2
```

With no settings yet, `dress list` prints one guidance line and exits 0:

```bash
$ python3 gristmill.py dress list
No dress settings yet — add one with: gristmill dress add --stone <name> --pattern <name> --gap <mil>
```

## 2. Log a grind run

Weigh the grain in and the flour out; GristMill computes and stores the yield.

```bash
$ python3 gristmill.py run add --dress 1 --grain-g 1000 --flour-g 718
Added run 1 with yield 71.8%

$ python3 gristmill.py run add --dress 2 --grain-g 1000 --flour-g 762
Added run 2 with yield 76.2%

$ python3 gristmill.py run list
ID  DRESS  GRAIN(g)  FLOUR(g)  YIELD%
──  ─────  ────────  ────────  ──────
 1      1      1000       718   71.8%
 2      2      1000       762   76.2%
```

The stored yield is a fact about that grind: it is computed once at write time
(`flour/grain*100`, one decimal) and never recomputed on read.

Rejected before writing:

```bash
$ python3 gristmill.py run add --dress 1 --grain-g 500 --flour-g 600
gristmill: flour cannot exceed grain (flour 600 g, grain 500 g)

$ python3 gristmill.py run add --dress 99 --grain-g 1000 --flour-g 700
gristmill: no dress setting with id 99 — run 'gristmill dress list' to see the settings you have
```

## 3. Compare dress settings

```bash
$ python3 gristmill.py compare
RANK  DRESS  STONE        PATTERN        GAP(mil)  RUNS  MEAN YIELD%
────  ─────  ───────────  ─────────────  ────────  ────  ───────────
   1      2  French Burr  fine dress            8     2        75.8%
   2      1  French Burr  3/4 dress            12     2        71.1%
   3      3  Peak         cracked dress        16     2        68.1%
```

Rank 1 is the highest mean yield. Ties are broken by the lower dress id, so two
identical invocations always print the same ranking. With no runs stored:

```bash
$ python3 gristmill.py compare
No grind runs to compare yet — log a run with: gristmill run add --dress <id> --grain-g <g> --flour-g <g>
```

## 4. Keep more than one notebook

`--file` goes before the subcommand and works on every command:

```bash
$ python3 gristmill.py --file ~/notebooks/spring-2026.json dress add --stone Peak --pattern cracked --gap 16
Added dress 1

$ python3 gristmill.py --file ~/notebooks/spring-2026.json compare
No grind runs to compare yet — log a run with: gristmill run add --dress <id> --grain-g <g> --flour-g <g>
```

The default notebook `~/.gristmill.json` is untouched by those commands.

## 5. When a notebook is damaged

A notebook that is not valid JSON stops the command with one line on stderr,
exit code 3, and the file left byte-for-byte as it was — fix it by hand or
move it aside and start a new one:

```bash
$ python3 gristmill.py --file /tmp/gm/bad.json dress list
gristmill: data file /tmp/gm/bad.json is not valid JSON and was left untouched
$ echo $?
3
```

## 6. Scripting

Results go to stdout, errors to stderr, and exit codes are `0` success,
`2` usage/validation, `3` unreadable notebook — so a shell script can act on
them:

```bash
python3 gristmill.py compare > ranking.txt || echo "compare failed" >&2
```
