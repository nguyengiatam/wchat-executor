#!/usr/bin/env python3
"""Thin, stdlib-only Claude Code adapter for wchat run's versioned JSON API."""

import argparse
import json
import os
import re
import signal
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

KNOWN_SCHEMA = 1
START_TIMEOUT_SECONDS = 120
RUN_ID = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
PROVIDER = re.compile(r"[a-z0-9_-]{1,32}\Z")
VERSION = re.compile(r"(?:wchat\s+)?(\d+)\.(\d+)\.(\d+)")


class WchatUnavailable(Exception):
    """An explicitly selected wchat binary cannot be executed."""


def run_id(value):
    if not RUN_ID.fullmatch(value):
        raise argparse.ArgumentTypeError("run id must match ^[0-9A-Za-z_-]{1,64}$")
    return value


def provider_name(value):
    if not PROVIDER.fullmatch(value):
        raise argparse.ArgumentTypeError("provider must match ^[a-z0-9_-]{1,32}$")
    return value


# Flags the plugin itself sets or checks; never accepted after "--".
RESERVED_FLAGS = frozenset(("--resume", "--provider", "--workspace", "--run-id", "--json",
                            "--task-file", "--config"))


def wchat_binary():
    """An explicit WCHAT_BIN is authoritative, including when it is broken."""
    explicit = "WCHAT_BIN" in os.environ
    selected = os.environ.get("WCHAT_BIN") if explicit else "wchat"
    if not selected:
        raise WchatUnavailable("WCHAT_BIN is empty; refusing PATH fallback")
    if os.path.sep in selected or (os.path.altsep and os.path.altsep in selected):
        path = os.path.abspath(os.path.expanduser(selected))
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    else:
        found = shutil.which(selected)
        if found:
            return found
    if explicit:
        raise WchatUnavailable("WCHAT_BIN cannot be executed: " + selected + "; refusing PATH fallback")
    raise WchatUnavailable("wchat not installed: no wchat found in PATH")


def invoke(binary, *args, stdin=None, timeout=None):
    return subprocess.run([binary, *args], stdin=stdin, capture_output=True, timeout=timeout)


def invoke_interruptible(binary, *args):
    """Reap the read-only wait child if Claude Code interrupts its wrapper."""
    child = subprocess.Popen([binary, *args], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    previous = {}

    def interrupted(signum, _frame):
        if child.poll() is None:
            child.terminate()
        try:
            child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
        raise SystemExit(128 + signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        stdout, stderr = child.communicate()
        return subprocess.CompletedProcess([binary, *args], child.returncode, stdout, stderr)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def output(raw, stream=sys.stdout):
    stream.write(raw.decode("utf-8", "replace"))
    stream.flush()


def error(message):
    print(message, file=sys.stderr)
    return 2


def parse_json(raw):
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError):
        return None, "wchat returned invalid JSON"
    if not isinstance(value, dict):
        return None, "wchat returned JSON that is not an object"
    if type(value.get("schema")) is not int or value["schema"] != KNOWN_SCHEMA:
        return None, "wchat returned unknown schema {!r}, update wchat-executor".format(value.get("schema"))
    return value, None


def fetch(binary, *args):
    try:
        response = invoke(binary, "run", *args, "--json")
    except OSError as exc:
        return None, error("cannot run wchat: " + str(exc))
    if response.returncode:
        output(response.stderr, sys.stderr)
        return None, response.returncode
    value, problem = parse_json(response.stdout)
    if problem:
        return None, error(problem)
    return value, 0


def uncertain_start(workspace, problem):
    print("Run existence unconfirmed: " + problem)
    command = "python3 {} status".format(shlex.quote(str(Path(__file__).resolve())))
    print("Check in the workspace that was used; do NOT re-dispatch:")
    print("cd {} && {}".format(shlex.quote(workspace), command))
    print("WCHAT_START=unknown")
    return 1


def exec_run(args, agent_flags):
    workspace = os.path.realpath(os.path.abspath(args.workspace or os.getcwd()))
    if args.task_file:
        try:
            task = open(args.task_file, "rb")
        except OSError as exc:
            return error("cannot read task file: " + str(exc))
    else:
        task = None
    try:
        binary = wchat_binary()
    except WchatUnavailable as exc:
        if task is not None:
            task.close()
        return error(str(exc))

    if args.resume:
        previous, rc = fetch(binary, "status", args.resume)
        if rc:
            return rc
        if previous.get("provider") != args.provider:
            return error("run {!r} provider is {!r}, does not match {!r}; not resuming".format(
                args.resume, previous.get("provider"), args.provider))

    command = ["run", "start", *agent_flags, "--provider", args.provider,
               "--workspace", workspace, "--json"]
    if args.resume:
        command += ["--resume", args.resume]
    try:
        # A task is never interpolated into a shell command or passed in argv.
        response = invoke(binary, *command, stdin=task if task is not None else subprocess.DEVNULL,
                          timeout=START_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return uncertain_start(workspace, str(exc))
    finally:
        if task is not None:
            task.close()
            try:
                os.unlink(args.task_file)
            except OSError as exc:
                print("Could not remove task file: " + str(exc), file=sys.stderr)

    if response.returncode:
        if b"start unconfirmed" in response.stderr.lower():
            return uncertain_start(workspace, response.stderr.decode("utf-8", "replace").strip())
        output(response.stderr, sys.stderr)
        print("WCHAT_START=refused")
        return response.returncode
    value, problem = parse_json(response.stdout)
    if problem:
        return uncertain_start(workspace, problem)
    identity = value.get("run")
    if not isinstance(identity, str) or not RUN_ID.fullmatch(identity):
        return uncertain_start(workspace, "wchat did not return a valid run id")
    if response.stderr:
        output(response.stderr, sys.stderr)  # Warnings are never parsed as JSON.
    print("Created run {} in {}".format(identity, workspace))
    print("WCHAT_START=created RUN=" + identity)
    return 0


def status_run(args):
    binary = wchat_binary()
    if args.run:
        value, rc = fetch(binary, "status", args.run)
        if rc:
            return rc
        print("Run: {}\nStatus: {}\nProvider: {}\nWorkspace: {}".format(
            value.get("run"), value.get("status"), value.get("provider"), value.get("workspace")))
        return 0
    value, rc = fetch(binary, "list")
    if rc:
        return rc
    workspace = os.path.realpath(os.getcwd())
    runs = value.get("runs")
    if not isinstance(runs, list):
        return error("wchat returned an invalid run list")
    for item in runs:  # wchat's newest-first order is authoritative.
        if not isinstance(item, dict) or not isinstance(item.get("workspace"), str):
            continue
        if os.path.realpath(item["workspace"]) == workspace:
            print("{} {} {}".format(item.get("run"), item.get("status"), item.get("updated")))
    return 0


def wait_run(args):
    binary = wchat_binary()
    command = ["run", "wait", args.run, "--json"]
    if args.timeout is not None:
        command += ["--timeout", args.timeout]
    try:
        response = invoke_interruptible(binary, *command)
    except OSError as exc:
        return error("cannot run wchat: " + str(exc))
    if response.stderr:
        output(response.stderr, sys.stderr)
    if not response.stdout:
        return response.returncode or error("wchat wait returned no JSON")
    value, problem = parse_json(response.stdout)
    if problem:
        return error(problem)
    print("Run: {}\nStatus: {}\nExit code: {}".format(
        value.get("run"), value.get("status"), response.returncode))
    if response.returncode == 7:
        print("Still running; not a terminal state. Check: status {} or wait {}".format(
            args.run, args.run))
    elif value.get("status") in ("retryable", "stopped"):
        provider = value.get("provider")
        if isinstance(provider, str) and PROVIDER.fullmatch(provider):
            print("Can resume manually: exec --provider {} --resume {}".format(provider, args.run))
        else:
            print("Check the provider before resuming run {}".format(args.run))
    elif value.get("status") == "needs_human":
        print("Needs a human to check the conversation first; if you are sure the turn/action had no effect, resume manually: "
              "exec --provider {} --resume {}. Do not re-dispatch.".format(value.get("provider"), args.run))
    elif value.get("status") == "rate_limited":
        print("Provider rate-limited; this run cannot be resumed — dispatch a new run with exec when you want. "
              "Do not re-dispatch.")
    else:
        print("Check the result: result {}".format(args.run))
    return response.returncode


def result_run(args):
    binary = wchat_binary()
    value, rc = fetch(binary, "result", args.run)
    if rc:
        return rc
    print("Status: {} (run {})".format(value.get("status"), value.get("run")))
    git = value.get("git") if isinstance(value.get("git"), dict) else {}
    print("Commit:")
    commits = git.get("commits")
    if git.get("available") is True and isinstance(commits, list):
        if commits:
            for item in commits:
                if isinstance(item, dict):
                    print("  {} {}".format(item.get("sha"), item.get("subject")))
        else:
            print("  no commit")
    else:
        print("  unknown: {}".format(git.get("error") or "no Git evidence"))
    if git.get("bounded") is False:
        print("  no final boundary yet (bounded: false)")
    print("Shell commands:")
    shell = value.get("shell")
    if isinstance(shell, list) and shell:
        for item in shell:
            if not isinstance(item, dict):
                print("  unknown: invalid record")
                continue
            code = item.get("exit")
            state = item.get("status")
            if code is None:
                print("  {}: exit: null; status: {}".format(item.get("cmd"), state or "unknown"))
            else:
                print("  {}: exit: {}; status: {}".format(item.get("cmd"), code, state))
    else:
        print("  no shell command records")
    print("Final answer:")
    print(value.get("answer") if value.get("answer") is not None else "no final answer")
    if value.get("error"):
        print("Recorded error: " + str(value["error"]))
    return 0


def cancel_run(args):
    binary = wchat_binary()
    try:
        response = invoke(binary, "run", "stop", args.run, "--json")
    except OSError as exc:
        return error("cannot run wchat: " + str(exc))
    if response.returncode:
        if b"stop unconfirmed" in response.stderr.lower():
            output(response.stderr, sys.stderr)
            print("Stop unconfirmed; not inferring run {} state".format(args.run))
        else:
            output(response.stderr, sys.stderr)
        return response.returncode
    value, problem = parse_json(response.stdout)
    if problem:
        return error(problem)
    print("Run: {}\nStatus after stop: {}".format(value.get("run"), value.get("status")))
    return 0


def setup_run(_args):
    try:
        binary = wchat_binary()
    except WchatUnavailable as exc:
        return error(str(exc))
    try:
        version = invoke(binary, "--version")
    except OSError as exc:
        return error("wchat not installed: " + str(exc))
    if version.returncode:
        output(version.stderr, sys.stderr)
        return version.returncode
    found = VERSION.search(version.stdout.decode("utf-8", "replace"))
    if not found:
        return error("cannot read wchat version; requires wchat ≥ 0.7.0 with wchat run")
    if tuple(map(int, found.groups())) < (0, 7, 0):
        return error("requires wchat ≥ 0.7.0 with wchat run; current: " + found.group(0))
    try:
        doctor = invoke(binary, "doctor")
    except OSError as exc:
        return error("cannot run wchat doctor: " + str(exc))
    output(doctor.stdout)
    output(doctor.stderr, sys.stderr)
    if doctor.returncode:
        return doctor.returncode
    print("wchat {}: doctor OK".format(found.group(0)))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    agent_flags = []
    if argv and argv[0] == "exec" and "--" in argv:
        separator = argv.index("--")
        agent_flags = argv[separator + 1:]
        argv = argv[:separator]
        # The plugin owns these; passing them through would skip its checks
        # (a passthrough --resume bypassed the provider match, review D1).
        for flag in agent_flags:
            if flag.split("=", 1)[0] in RESERVED_FLAGS:
                return error("flag {} belongs to the plugin, must not be set after --".format(flag.split("=", 1)[0]))
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("exec", help="start or resume a detached wchat run")
    execute.add_argument("--provider", required=True, type=provider_name)
    choose = execute.add_mutually_exclusive_group(required=True)
    choose.add_argument("--task-file")
    choose.add_argument("--resume", type=run_id)
    execute.add_argument("--workspace")
    waiting = commands.add_parser("wait", help="wait for run's final status")
    waiting.add_argument("run", type=run_id)
    waiting.add_argument("--timeout")
    showing = commands.add_parser("status", help="show a run or list runs in this workspace")
    showing.add_argument("run", nargs="?", type=run_id)
    results = commands.add_parser("result", help="show all recorded run evidence")
    results.add_argument("run", type=run_id)
    cancelling = commands.add_parser("cancel", help="request safe stop")
    cancelling.add_argument("run", type=run_id)
    commands.add_parser("setup", help="check installed wchat and doctor")
    args = parser.parse_args(argv)
    try:
        return {"exec": lambda: exec_run(args, agent_flags), "wait": lambda: wait_run(args),
                "status": lambda: status_run(args), "result": lambda: result_run(args),
                "cancel": lambda: cancel_run(args), "setup": lambda: setup_run(args)}[args.command]()
    except WchatUnavailable as exc:
        return error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
