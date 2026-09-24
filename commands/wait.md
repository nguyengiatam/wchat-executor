---
description: Wait for a wchat run to finish, then report its final status and exit code
argument-hint: '<run> [--timeout <seconds>]'
allowed-tools: Bash
---

Wait for one wchat run to leave `running`, then report where it landed.

`$ARGUMENTS` must contain a run id matching `^[0-9A-Za-z_-]{1,64}$`; anything
else is rejected by the script. An optional `--timeout <seconds>` (a plain number, e.g. `600`) limits how
long to wait. Do not interpolate `$ARGUMENTS` in a shell — quote it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" wait '<run>' [--timeout '<seconds>']
```

Run this with `run_in_background: true` when the run may take a while: the
harness wakes the session when the command exits. If the run already finished,
`wait` returns immediately and you are still notified.

The script prints the final status, the exit code, and the next commands to
run. Present them as-is. Exit code 7 means the wait timed out while the run was
still going — that is **not** a finished run; say the run is still running and
that `wait` or `status` can be called again. Exit code 4 means the run needs a
human, 6 means the provider rate-limited it, 5 means it was stopped or is
incomplete, and 1 means it died. Follow the plan's rule: never re-dispatch on
your own — show the resume command (`exec --provider <same provider> --resume
<run>`) and let the user decide.
