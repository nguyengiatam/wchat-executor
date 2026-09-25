---
name: wchat-cli-runtime
description: Use when invoking or debugging the wchat CLI as a headless coding executor through the wchat-executor plugin - documents the required provider, the run statuses and their exit codes, the schema-versioned JSON, and the traps around resume, stopping, and editing wchat itself.
---

# wchat CLI Runtime Contract

`wchat run` is wchat's detached-executor surface (AC2). The `wchat_executor.py`
companion builds the commands and reads the JSON; this skill is the source of
truth for the flags, the statuses, and the traps.

## The commands

```
wchat run start  [--provider P] [--workspace DIR] [--resume RUN] [--max-rounds N]
                 [--session S] [--new] [--on-sleep {pause,keep,fail}] [--json]
wchat run status RUN [--json]
wchat run wait   RUN [--json] [--timeout S]
wchat run result RUN [--json]
wchat run stop   RUN [--json]
wchat run list   [--json]
```

The task always goes to `start` on **stdin** — never as an argument, and never
through a shell. The plugin writes the task to a file outside the workspace and
lets the script feed that file to `start`'s stdin.

## The provider is required

Every dispatch names its provider; there is no default and no fallback. On a
resume, the provider must match the run's recorded provider, or the dispatch is
refused before anything is created. `wchat` itself accepts
`--provider {chatgpt,gemini,grok,deepseek,qwen,zai}`.

## Parallel runs are normal

Several runs may be in flight at once, on different providers **and** on the same
provider: each run has its own session, tab and conversation, and wchat's locks
keep them apart. Do not wait for one run to finish before dispatching the next,
and do not switch provider just because that provider already has a run going.
wchat spaces the sends of same-provider runs by itself (`throttle.<provider>`).
Do not reuse one `--session` for two runs at once - a session runs one turn at a
time.

## JSON is versioned

Every `wchat run ... --json` object carries `schema: 1`. The plugin only reads
schema 1; any other number means the plugin is older than wchat and must be
updated. Only **stdout** is parsed — wchat prints warnings (for example about an
unverified provider) to stderr, and those are never JSON.

## Statuses and exit codes (AC2 §4)

| status | exit | meaning |
|---|---|---|
| `done` | 0 | finished successfully |
| `died` | 1 | the run process died |
| `retryable` | 3 | the provider refused; a retry may work |
| `needs_human` | 4 | the turn may have been sent; a human must check |
| `incomplete` | 5 | the run ended without a final answer |
| `stopped` | 5 | stopped at a safe point |
| `rate_limited` | 6 | the provider rate-limited the turn |
| (wait timed out) | 7 | still running — **not** a finished run |

The plugin's `wait` exits with the code of `wchat run wait`, so these codes
reach the caller unchanged. Code 7 is presented as "still running".

## Stop stops at a safe point

`wchat run stop` signals the run and waits for it to go. A shell command already
running finishes first. `stop` reports the real outcome: `stopped`, a
`needs_human` turn that may have been sent, a final outcome already recorded
before the stop landed, or "stop unconfirmed" when wchat's own message says so.
The plugin prints the outcome wchat reports and never invents one.

## wchat's browser

wchat drives its **own** browser profile under `~/.wchat`, never the user's
browser. From wchat 0.8.0 every run and `doctor` open or restart that browser
when it is not answering (one `wchat: browser lifecycle: ...` line on stderr).
Do not ask the user to start it, and never give them a raw browser command to run
through `!`: it would run in the foreground and hang the session. A profile
directory name does not say which providers are logged in.

## Traps

- **A run is never resumed automatically.** Report and show the next command;
  let the user decide:
  - `stopped`, `retryable` — `exec --provider <same> --resume <run>`;
  - `needs_human` — inspect the conversation first; only if the turn or
    operation had no effect, `exec --provider <same> --resume <run>`;
  - `rate_limited` — wchat refuses to resume it; dispatch a new run with `exec`.
- **`--resume` carries no new task.** wchat ignores stdin on a resume, so the
  plugin refuses `--resume` combined with a task file.
- **Sending cadence.** A run with no keyboard sends on a roughly 20-second
  cadence, and a long run costs real wall-clock time. Do not poll; start `wait`
  once and let the harness wake the session.
- **Editing wchat itself through wchat.** Running a task that edits the wchat
  repository through wchat means the run may rewrite the very code it is running
  on. Run such work from a runner copy (LESSONS "Sửa chính wchat"); the plugin
  does not handle this for you.
- **DeepSeek.** Prefer small, multi-round edits when the provider is deepseek
  (LESSONS).

## How the plugin uses it

`/wchat-executor:exec` (or the `wchat-runner` subagent) builds all of the above.
Use `/wchat-executor:status`, `:result`, `:cancel`, and `:setup` to manage runs.
The plugin keeps no job state of its own: every fact comes from `wchat run`.
