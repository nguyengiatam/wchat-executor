---
name: wchat-task-briefing
description: Use when writing the task text for a wchat run (exec --task-file) or choosing which provider to hand it to - the briefing rules that keep a web-chat executor on task, and the measured per-provider traps (DeepSeek, ChatGPT, MiMo, Qwen, Gemini, Grok, Z.ai, Kimi) that make a well-meant brief fail.
---

# Briefing a wchat executor

A wchat run is a model in a chat web page, reaching the workspace only through
the ops it asks for. It forgets, it wanders, and each provider's site adds its
own traps. Most failed runs trace back to the brief, not the model. Everything
below was measured on real runs; each provider note carries its date and
evidence, and anything not measured is marked so.

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

Results over either limit go as an attached file.

| provider | lines | chars | agent support |
|---|---|---|---|
| chatgpt | 200 | 200,000 | supported |
| gemini, grok, deepseek, qwen, zai | 400 | 200k-500k | supported |
| mimo | 1000 | 100,000 | supported (0.12.0+) |
| kimi | 400 | 200,000 | unverified (`--unverified-provider`) |

## Per-provider notes

**DeepSeek** — fast on small, well-pointed tasks (~10-15 min). Needs the
small-edit-turn rule (5). Sends are paced 20 s apart in the user's config; two
DeepSeek runs dispatched at the same time both died `rate_limit_reached`
(exit 6, not resumable) on 2026-09-26 — cause not yet investigated. A turn
where DeepSeek only "thinks" and returns no answer ends `needs_human` and does
not resume: dispatch a new session.

**ChatGPT** (paid account in wchat's browser) — the most dependable for long
tasks, reviews and live measurements on 2026-09-26 (about a dozen runs, no
delivery failure after wchat 0.9.1). It follows "stop and report if X" rules
literally, which is what you want. For read-only review, run it on a `git
clone` in a scratch directory: wchat has no read-only mode.

**MiMo** (Xiaomi MiMo AI Studio) — has a content filter that checks the prompt
AND the model's own output (`event:sensitive_query`, reported by wchat 0.12.1+
as "MiMo refused the turn (content filter ...)"). Measured 2026-09-26: a brief
granting permission to read another repository with shell `cat` plus "this is
not bypassing the rules" was refused on the first turn; a brief pointing at
files outside the workspace was cut mid-reply while the model reasoned about
reading them with `cat`. Give MiMo small, self-contained tasks inside the
workspace (rules 1, 6, 7). Models: `--model pro|flash`; no thinking control.
Free plan has a daily token limit (amount not measured).

**Qwen** — its thinking mode sometimes calls Qwen's own tools (code
interpreter) instead of answering with a c2c block and loops; `--thinking fast`
had a send bug on 2026-09-26. It once took an attached file for a workspace
file. Keep turns under the inline limit.

**Gemini** — prefer the Flash model: Pro was weaker and slower on these tasks.
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

Read the run's status and its raw capture before blaming the model: `rate_limited`
(exit 6) is the site refusing; "content filter" is the brief; an answer that
says "I don't see a task" is results that went out as an attachment (rules 2-3);
many rounds of reads with no edit is a brief too big (rule 4).
