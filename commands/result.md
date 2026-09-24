---
description: Show a wchat run's structured result - status, commits, shell commands and exit codes, and the final answer
argument-hint: '<run>'
allowed-tools: Bash
---

Show the structured result of one finished or unfinished wchat run.

The run id must match `^[0-9A-Za-z_-]{1,64}$`. Quote it; never let the shell
interpolate `$ARGUMENTS`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" result '<run>'
```

The script reads `wchat run result --json` and presents four groups; every
group is shown, none is dropped:

- **status** — the run's derived status as wchat reports it;
- **git** — the commits the run made. `available: false`, or `commits: null`,
  means the evidence is unknown and the script prints the git error: say
  "unknown", not "no commits". Only when git is available and `commits` is an
  empty list does the script say "no commits". `bounded: false` means no final
  boundary was recorded, so the commit list may be incomplete — say so.
- **shell** — the commands the run started and their exit codes. An `exit` of
  `null` is not success: print the status instead (`uncertain` when the outcome
  was never seen, `unavailable` when it was never bounded).
- **answer** — the run's final answer.

Present all of it verbatim. Do not summarise away a gap; a missing fact is a
finding, not something to smooth over. If the schema is unknown, say the plugin
needs updating.
