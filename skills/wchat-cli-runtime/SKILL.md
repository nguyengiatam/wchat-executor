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
                 [--session S] [--new] [--on-sleep {pause,keep,fail}]
                 [--model M] [--thinking T] [--json]
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
`--provider {chatgpt,gemini,grok,deepseek,qwen,zai,kimi,mimo}`.

## Kimi and MiMo are unverified providers (wchat 0.9.0+ / 0.10.0+)

`kimi` has run for real (a one-shot ask, a named session, an agent reading files
through c2c) but its delivery is not yet measured, so wchat refuses it unless the
agent options carry `--unverified-provider`, and it prints a warning to stderr on
every run. The flag is not remembered by the run: pass it again on a resume
(`exec --provider kimi --resume <run> -- --unverified-provider`). On wchat main
after 0.9.0, Kimi takes `--model k3|k2.8|instant` and `--thinking
standard|advanced|max` (`max` spends extra credits). K3 and K2.8 may need a paid
Kimi plan, and at peak hours Kimi refuses free accounts on every model: since wchat
0.10.0 the run then ends `rate_limited` (exit 6) with "Kimi is overloaded and is
refusing free-plan requests right now (REASON_SERVER_OVERLOADED_FOR_FREE_USER); retry
later" - dispatch again later or use another provider. `instant` is the safe model on a
free account. Kimi keeps the composer draft, attached file
cards included, across tabs: a failed turn can leave cards that get sent with the
next turn.

`mimo` (Xiaomi MiMo AI Studio, wchat 0.10.0+) is unverified the same way: pass
`--unverified-provider` on every start and resume. From wchat 0.11.0 it takes
`--model pro|flash`; it has no thinking control, so `--thinking` is refused. The free
plan has a daily token limit. When a turn's ops results are too long and go as an
attached file, MiMo tends to treat the file as reference material and lose the task
(it may re-read files or `task.md` before answering) - keep MiMo tasks small.

## Model and thinking mode (wchat 0.9.0+)

`--model` and `--thinking` go to `start` as agent options. Only gemini, qwen, zai,
kimi and mimo accept `--model` (`--thinking`: gemini, qwen, zai, kimi); any other provider is refused before
anything is sent. A model the page does not offer is **not** an error: the run
uses the page's own model and stderr says `model '<asked>' not available`. Names
match an id, the menu label, the site id, an alias (`pro`, `flash`, `max`) or the
last word of a label - `wchat models list` shows them. On Gemini the choice is the
account's default for every tab, so parallel Gemini runs with different models
overwrite each other's default (wchat re-selects before every send).

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
