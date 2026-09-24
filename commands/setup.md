---
description: Check that wchat is installed, new enough to have `wchat run`, and that its browser answers doctor
argument-hint: ''
allowed-tools: Bash
---

Verify the wchat install this plugin depends on:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wchat_executor.py" setup
```

The script checks three things and prints one message per failure:

- `wchat --version` missing ⇒ "wchat is not installed" — tell the user to
  install wchat and put it on PATH;
- version below 0.7.0 ⇒ "wchat 0.7.0 or newer is required (it has `wchat run`)" —
  tell the user to upgrade;
- `wchat doctor` failing ⇒ print wchat's error **verbatim**. Do not diagnose the
  cause yourself: a broken config and a browser that will not answer look the
  same from here, and only wchat can tell them apart.

Present the result as-is. This command never starts a run and never touches the
user's browser.
