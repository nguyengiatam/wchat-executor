# wchat-executor

A Claude Code plugin that dispatches the **wchat CLI** (`wchat run`) as a
background coding executor - one provider named per dispatch, detached runs
with durable status, wake-on-finish, and JSON that is versioned so a schema
mismatch is reported instead of guessed. Sibling to `devin-executor` and
`agy-executor`, same shape, different CLI.

## Install

```
/plugin marketplace add https://github.com/nguyengiatam/wchat-executor.git
/plugin install wchat-executor@wchat-executor-marketplace
```

## Requirements

The `wchat` CLI must be installed and on your PATH, version 0.7.0 or newer (the
version that has `wchat run`). Run `/wchat-executor:setup` to verify the
version and that `wchat doctor` answers.

## Commands

| Command | Purpose |
|---------|---------|
| `/wchat-executor:exec --provider P <task>` | Dispatch a task to wchat, then get woken when it finishes. |
| `/wchat-executor:wait <run>` | Wait for a run and report its final status and exit code. |
| `/wchat-executor:status [run]` | One run, or the runs whose workspace is this repository, newest first. |
| `/wchat-executor:result <run>` | Structured result: status, commits, shell commands + exit codes, final answer. |
| `/wchat-executor:cancel <run>` | Stop a run and report the real outcome wchat reports. |
| `/wchat-executor:setup` | Check the wchat install and health. |

Claude can also delegate to the `wchat-executor:wchat-runner` subagent, which
forwards a task to the runtime.

## Why a wrapper

- **The provider is mandatory.** There is no default and no fallback; a
  dispatch without one is refused before anything is created.
- **The task never touches a shell.** It is written to a file outside the
  workspace with the `Write` tool and fed to `wchat run start` on stdin, so
  newlines, quotes, `$(...)`, and semicolons arrive byte-for-byte.
- **Three outcomes, named honestly.** `created` (here is the run id),
  `refused` (wchat said no; here is its error), or `unknown` (the result of
  `start` was lost) - and on `unknown` the plugin never dispatches again; it
  tells you to check with `status`.
- **The JSON is versioned.** Only `schema: 1` is read; anything else means the
  plugin needs updating, and it says so instead of presenting a status.
- **Wake on finish.** After a dispatch, the plugin starts `wait` in the
  background so the session is notified when the run leaves `running` - even if
  it had already finished.

## What it does not do

The plugin keeps no job state of its own - every fact comes from `wchat run`.
It never resumes or re-dispatches on its own, never switches provider, and
never opens or closes your browser.

## License

MIT.
