---
description: Show one wchat run, or the wchat runs whose workspace is this repository
argument-hint: '[<run>]'
allowed-tools: Bash
---

Show a wchat run's durable status.

With no id, list the runs whose workspace is the current repository, newest
first. With an id (`^[0-9A-Za-z_-]{1,64}$`), show that one run in full. Quote
the argument; never let the shell interpolate `$ARGUMENTS`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" status ['<run>']
```

The script reads `wchat run status --json` or `wchat run list --json` and
filters by realpath equality against the current directory — it does not
prefix-match, so `/repo` and `/repo-other` never mix.

Present the output as a compact table or list. Do not add a status the script
did not print, and do not call `wchat` yourself. If the script reports that the
JSON schema is unknown, tell the user the plugin needs updating for this wchat.
