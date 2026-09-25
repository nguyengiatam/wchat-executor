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

wchat has its **own** browser: a dedicated profile under `~/.wchat`, separate from
the browser the user works in. From wchat 0.8.0, `wchat doctor` (and every run)
opens or restarts that browser by itself when it is not answering, and prints a
`Browser lifecycle:` line saying what it did. So:

- never hand the user a raw browser command to run, least of all through `!` - a
  browser started that way runs in the foreground and hangs the session;
- if doctor still fails because nothing answers on the port and the version is
  below 0.8.0, the fix is upgrading wchat, not starting the browser by hand;
- a profile directory's name (for example `chrome-profile-grok`) says nothing
  about which providers are logged in; the provider is always named per dispatch.

Present the result as-is. This command never starts a run and never touches the
user's own browser.
