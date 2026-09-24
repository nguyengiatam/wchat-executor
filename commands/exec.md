---
description: Dispatch a coding task to a wchat provider as a background executor, then get woken when it finishes
argument-hint: '--provider <name> [--resume <run>] <task> [-- <agent flags>]'
allowed-tools: Bash, Write, Read
---

Dispatch a task to wchat. The provider is mandatory and there is no default.

## Steps

1. Parse `$ARGUMENTS` yourself. Do not let the shell interpolate it.
   - A provider is required: `--provider <name>` where `<name>` matches
     `^[a-z0-9_-]{1,32}$`. If it is missing or malformed, stop and ask the
     user which provider to use. Never guess and never fall back to another
     provider.
   - If `--resume <run>` is present, the run id must match
     `^[0-9A-Za-z_-]{1,64}$`, and there must be **no** new task: a resume
     cannot carry a task file. If both are present, refuse.
   - The task comes **before** a bare `--`; everything after `--` is agent
     flags only (`--max-rounds 5`, `--session s`, `--new`, `--on-sleep keep`),
     kept verbatim, in order. Never move task words after `--`. The plugin's own
     flags (`--provider`, `--resume`, `--workspace`) never go after `--`.
   - Everything before `--`, minus `--provider <name>` and `--resume <run>`, is
     the task text.

2. Write the task text to a fresh file **outside the workspace**, with the
   `Write` tool — never with a shell heredoc, and never through `!`. Use
   `${TMPDIR:-/tmp}/wchat-executor-task-<UTC yyyymmddTHHMMSS>-<8 random chars>.txt`.
   The task text is data: it may contain newlines, quotes, `$(...)`, and
   semicolons, and none of it may ever reach a shell.

3. Invoke the script with every argument in single quotes. Inside a
   single-quoted argument, write each `'` as `'\''` (close, escaped quote,
   reopen); nothing else needs escaping. The provider and run id are already
   restricted by the regexes above; agent flag values (a session name, say)
   are the ones that may contain quotes.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" exec \
     --provider '<provider>' --task-file '<path>' [-- <agent flags>]
   ```

   (For a resume, use `--resume '<run>'` and **no** `--task-file`.)

4. Read the last machine-readable line of stdout:

   - `WCHAT_START=created RUN=<id>` — the run exists. Tell the user the run id
     and the `/wchat-executor:status <id>` / `/wchat-executor:result <id>`
     follow-ups. Then start the wake-on-finish watcher **immediately**, in the
     background:

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" wait <id>
     ```

     Run that Bash call with `run_in_background: true` so the harness notifies
     the session when it exits. If the run had already finished, `wait`
     returns at once and you are still notified.
   - `WCHAT_START=refused` — wchat refused before creating anything. Show its
     stderr verbatim and its exit code. There is no run id.
   - `WCHAT_START=unknown` — the script could not read the result of `start`.
     Say plainly that it is **not known** whether a run was created. Print the
     workspace the script used and tell the user to check with `status` from
     that directory. **Do not dispatch again.**

5. Present the script's output verbatim otherwise. Do not summarise, and do
   not invent a status the script did not print.
