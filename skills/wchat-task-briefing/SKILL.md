---
name: wchat-task-briefing
description: Use when writing the task text for a wchat run (exec --task-file) or choosing which provider to hand it to - the briefing rules that keep a web-chat executor on task, and the measured per-provider traps (DeepSeek, ChatGPT, MiMo, Qwen, Gemini, Grok, Z.ai, Kimi) that make a well-meant brief fail.
---

# Briefing a wchat executor

A wchat run is a model in a chat web page, reaching the workspace only through
the ops it asks for. This skill collects the briefing practices and the dated
provider-specific limits observed on real runs (webchat-agent project,
September 2026). Observations are not guarantees: sites change, and an
anecdote is marked as one.

## Which provider

The order in which to try providers is each project's decision: follow the
project's own team/roster file, and ask the user before changing it. This
skill does not set it. Do not dispatch to a provider the user has put on hold
(currently Kimi and MiMo, for this user).

## Rules for every provider

1. **Self-contained brief.** Put what the executor needs in the task text:
   the goal, the exact files and functions to read, the mechanism to reuse,
   the tests to write, the commands to run, the report shape. Every "go read
   the spec to understand" costs rounds and invites wandering.
2. **Name the files; forbid orientation reads.** An executor left free reads
   README, CHANGELOG, git log, whole modules. Say "Read only these" and list
   files with line ranges. Measured: one run's results ballooned to 25k chars /
   603 lines from orientation reads, went out as an attachment, and the model
   concluded "I don't see a task" (webchat-agent LESSONS, 2026-09-22).
3. **Keep each round's results under the provider's inline limit** (table
   below). Over it, wchat sends the ops results as an attached file, and
   several models then lose track of the task. Ask for `head`/`tail`/`grep`,
   targeted line ranges, and short shell outputs. `--round-chars N` caps the
   data per round.
4. **Split by the files a change touches, not by requirements.** A brief that
   spans three modules gets read for ten rounds and dies before the first edit.
   One task = one checkpoint = one commit.
5. **Ask for small edit turns.** "Edit function X in one turn, tests in the
   next." Models that plan a whole-file rewrite in one turn run out of output.
6. **Workspace only.** Keep everything the executor must read inside
   `--workspace`. Copy external docs in, or paste the needed part into the
   brief. Reading outside the workspace is refused by the bridge, and on MiMo
   even asking for it trips the content filter (below).
7. **No self-justifying permission prose.** Sentences like "you are allowed to
   ..., this is not bypassing the rules" read as jailbreak framing to site
   filters. State the task plainly.
8. **Prove, don't claim.** Ask for command output pasted verbatim, mutation
   red lines for new tests, and a report that says what was NOT done.
9. **Browser-sharing rules** when the task touches Chrome/CDP (probes,
   measurements): sleep >= 1 s between calls to `http://127.0.0.1:<port>/json/*`,
   reuse one WebSocket per tab, open at most one tab and close exactly that tab
   by id, never close or navigate other tabs, and never start background
   processes with `&`/`nohup` inside a shell op (the op hangs to its timeout).
   Measured 2026-09-26: a watcher polling `/json/list` without sleeping
   exhausted local TCP ports and the shared browser was restarted under every
   other run.

## Inline limits (wchat 0.12.1)

Results over either limit go as an attached file. Source: each provider's
`capabilities` in `wchat/provider/<name>.py` (`max_inline_lines`,
`max_inline_prompt`); check your installed version if it differs.

| provider | lines | chars | agent support |
|---|---|---|---|
| chatgpt | 200 | 200,000 | supported |
| gemini | 400 | 500,000 | supported |
| grok | 400 | 200,000 | supported |
| deepseek | 400 | 500,000 | supported |
| qwen | 400 | 500,000 | supported |
| zai | 400 | 200,000 | supported |
| mimo | 1000 | 100,000 | supported (0.12.0+) |
| kimi | 400 | 200,000 | unverified (`--unverified-provider`) |

## Per-provider notes

**DeepSeek** — fast on small, well-pointed tasks (~10-15 min). Needs the
small-edit-turn rule (5). Put this sentence in every DeepSeek brief: "Every
workspace request is a fenced ```c2c JSON block; never DSML/XML or your own
tool-call syntax" — on a long task it once drifted to `<｜｜DSML｜｜ invoke>`,
which wchat reads as a final answer (2026-09-22). Sends are paced 20 s apart in the user's config; two
DeepSeek runs dispatched at the same time both died `rate_limit_reached`
(exit 6, not resumable) on 2026-09-26 — cause not yet investigated. A turn
where DeepSeek returned only thinking and no answer ended `needs_human` and did
not resume (2026-09-26); read the raw capture before concluding that, because
earlier "never reported finished" failures were a wchat decoder bug (fixed
2026-09-25, `8ffe362`). If the status really is an unresumable `needs_human`,
dispatch a new session.

**ChatGPT** (paid account in wchat's browser) — the most dependable for long
tasks, reviews and live measurements on 2026-09-26 (about a dozen runs, no
delivery failure after wchat 0.9.1). wchat runs ChatGPT in parallel, but the
account does not like it: on 2026-09-25 several simultaneous ChatGPT runs with
many uploads got the account temporarily blocked ("unusual activity", >15
min, every retry failed; wchat reports `rate_limited`). Keep to 1-2 ChatGPT
runs at a time and do not resume into a block. It follows "stop and report if X" rules
literally, which is what you want. For read-only review, run it on a `git
clone` in a scratch directory: wchat has no read-only mode.

**MiMo** (Xiaomi MiMo AI Studio) — on hold for this user (2026-09-27) until MiMo
ships new models: not reliable enough. It has a content filter that checks the prompt
AND the model's own output (`event:sensitive_query`, reported by wchat 0.12.1+
as "MiMo refused the turn (content filter ...)"). Observed 2026-09-26 on two
runs of the same task: (1) the reply was cut in the middle of the model's
thinking, while it reasoned about reading files outside the workspace with
`cat`; (2) after a paragraph was added granting permission to read the other
repository with `cat` and saying "this is not bypassing the rules", the first
turn was refused. In ten isolation sends that paragraph tripped the filter only
as a whole (permission + "not bypassing" sentence, with its context); neither
part alone did, and an external path by itself was not shown to trigger it. A second trigger, isolated with six short probes the same day: the phrase
"thinking mode" in the brief (reading code that contains "thinking" was fine).
A third run on the wchat repository, whose brief avoided both, was refused on a
turn carrying only ops results; what in them tripped the filter was not
isolated. The filter can judge workspace data, which the brief cannot fully
control. Observations are from a handful of runs: MiMo has also been running
fine on another project's tasks. Give it small, self-contained tasks inside
the workspace (rules 1, 6, 7); if a run is refused, read the capture, reword or
move the task to another provider rather than resending it unchanged. Models: `--model pro|flash`; no thinking control.
Free plan has a daily token limit (amount not measured).

**Qwen** — its thinking mode sometimes calls Qwen's own tools (code
interpreter) instead of answering with a c2c block and loops; `--thinking fast`
had a send bug on 2026-09-26. It once took an attached file for a workspace
file. Keep turns under the inline limit.

**Gemini** — prefer the Flash model: the user found Pro weaker and slower on
these tasks (their observation, not a benchmark).
The model choice is account-wide, so parallel Gemini runs with different
`--model` values overwrite each other's default (wchat re-selects before every
send). Refusal `BardErrorInfo [1095]` is reported as `rate_limited`.

**Grok, Z.ai** — delivery measured supported; little run history beyond that.
Z.ai's Deep Think control is hidden in wchat's small window (`--thinking` may
not apply) and it refuses at peak hours with `MODEL_CONCURRENCY_LIMIT`
(`rate_limited`).

**Kimi** — on hold for this user (2026-09-26): free accounts are refused at
peak hours on every model (`REASON_SERVER_OVERLOADED_FOR_FREE_USER`, exit 6);
K3/K2.8 need a paid plan. Use `--model instant` if you must.

## When a run fails

Investigate before rewriting the brief: read the run status, its log, the raw
capture it names, and if needed the conversation in the page. Causes seen so
far, none of them certain from the symptom alone: `rate_limited` (exit 6) —
the site refused (quota, overload, account block); "content filter" — the site
moderated the prompt or the model's output; "I don't see a task" — often the
results went out as an attachment (rules 2-3), but also seen with a bad upload
note; many rounds of reads and no edit — often a brief too big (rule 4). wchat
itself has had delivery bugs that looked like model failures; the capture
tells them apart.
