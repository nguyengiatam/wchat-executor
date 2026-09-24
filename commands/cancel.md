---
description: Stop a running wchat run and report the real outcome wchat reports back
argument-hint: '<run>'
allowed-tools: Bash
---

Stop a wchat run.

The run id must match `^[0-9A-Za-z_-]{1,64}$`. Quote it; never let the shell
interpolate `$ARGUMENTS`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" cancel '<run>'
```

The script runs `wchat run stop <run> --json` and presents the **real outcome**
wchat reports, which is one of:

- `stopped` — the run was stopped at a safe point;
- `needs_human` — the run may have sent a turn, so a human must check;
- a final outcome already recorded before the stop landed (for example `done`);
- "stop unconfirmed" — only when wchat's stderr contains exactly its own
  `stop unconfirmed` message. Every other failure (pid mismatch, a chat run,
  no such run) is printed verbatim with its exit code, and is **not** called
  unconfirmed.

A `stop` stops at a safe point: a shell command already running finishes
before the run stops. Present the outcome as-is; do not guess beyond what the
script printed.
