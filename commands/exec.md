---
description: Dispatch a coding task to a wchat provider as a background executor, then get woken when it finishes
argument-hint: '--provider <name> [--workspace <dir>] [--resume <run>] [--max-rounds N] [--session S] [--new] [--on-sleep P] [--model M] [--thinking T] <task>'
allowed-tools: Bash, Write, Read
---

Dispatch a task to wchat. The provider is mandatory and there is no default.

## Steps

1. Parse `$ARGUMENTS` yourself, left to right. Do not let the shell interpolate it.
   **Options come first, the task is everything after them.** Read tokens from
   the start only while each is one of these options:
   - plugin options: `--provider <name>`, `--workspace <dir>`, `--resume <run>`;
   - agent options: `--max-rounds <N>`, `--session <S>`, `--new`, `--on-sleep <P>`,
     `--model <M>`, `--thinking <T>`.

   The first token that is not one of those options starts the task. From there
   on **everything is task text, verbatim** — including words that look like
   options (`--provider deepseek`, `--session`, a bare `--`): a task about a CLI
   often names its flags, and none of them may be removed or moved.
   - A provider is required and `<name>` must match `^[a-z0-9_-]{1,32}$`. If it
     is missing or malformed, stop and ask which provider to use. Never guess,
     never fall back.
   - `--resume <run>` needs a run id matching `^[0-9A-Za-z_-]{1,64}$` and **no**
     task text (a resume carries no new task). Task text with `--resume` ⇒ refuse.
   - `--workspace <dir>` is the repository the run works in; without it, the
     current directory. Never drop it.

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
     --provider '<provider>' [--workspace '<dir>'] --task-file '<path>' \
     [-- <agent options, each value quoted>]
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
