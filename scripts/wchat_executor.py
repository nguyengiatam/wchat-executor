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
    raise WchatUnavailable("chưa cài wchat: không tìm thấy wchat trong PATH")


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
        return None, "wchat trả JSON không hợp lệ"
    if not isinstance(value, dict):
        return None, "wchat trả JSON không phải object"
    if type(value.get("schema")) is not int or value["schema"] != KNOWN_SCHEMA:
        return None, "wchat trả hợp đồng schema {!r}, cần cập nhật wchat-executor".format(value.get("schema"))
    return value, None


def fetch(binary, *args):
    try:
        response = invoke(binary, "run", *args, "--json")
    except OSError as exc:
        return None, error("không chạy được wchat: " + str(exc))
    if response.returncode:
        output(response.stderr, sys.stderr)
        return None, response.returncode
    value, problem = parse_json(response.stdout)
    if problem:
        return None, error(problem)
    return value, 0


def uncertain_start(workspace, problem):
    print("Chưa xác định có run hay không: " + problem)
    command = "python3 {} status".format(shlex.quote(str(Path(__file__).resolve())))
    print("Kiểm tra trong workspace đã dùng; KHÔNG tự giao lại:")
    print("cd {} && {}".format(shlex.quote(workspace), command))
    print("WCHAT_START=unknown")
    return 1


def exec_run(args, agent_flags):
    workspace = os.path.realpath(os.path.abspath(args.workspace or os.getcwd()))
    if args.task_file:
        try:
            task = open(args.task_file, "rb")
        except OSError as exc:
            return error("không đọc được tệp việc: " + str(exc))
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
            return error("provider của run {!r} là {!r}, không khớp {!r}; không resume".format(
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
                print("Không xoá được tệp việc: " + str(exc), file=sys.stderr)

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
        return uncertain_start(workspace, "wchat không trả run id hợp lệ")
    if response.stderr:
        output(response.stderr, sys.stderr)  # Warnings are never parsed as JSON.
    print("Đã tạo run {} trong {}".format(identity, workspace))
    print("WCHAT_START=created RUN=" + identity)
    return 0


def status_run(args):
    binary = wchat_binary()
    if args.run:
        value, rc = fetch(binary, "status", args.run)
        if rc:
            return rc
        print("Run: {}\nTrạng thái: {}\nProvider: {}\nWorkspace: {}".format(
            value.get("run"), value.get("status"), value.get("provider"), value.get("workspace")))
        return 0
    value, rc = fetch(binary, "list")
    if rc:
        return rc
    workspace = os.path.realpath(os.getcwd())
    runs = value.get("runs")
    if not isinstance(runs, list):
        return error("wchat trả danh sách run không hợp lệ")
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
        return error("không chạy được wchat: " + str(exc))
    if response.stderr:
        output(response.stderr, sys.stderr)
    if not response.stdout:
        return response.returncode or error("wchat wait không trả JSON")
    value, problem = parse_json(response.stdout)
    if problem:
        return error(problem)
    print("Run: {}\nTrạng thái: {}\nMã thoát: {}".format(
        value.get("run"), value.get("status"), response.returncode))
    if response.returncode == 7:
        print("Vẫn đang chạy; chưa phải trạng thái kết thúc. Kiểm tra: status {} hoặc wait {}".format(
            args.run, args.run))
    elif value.get("status") in ("retryable", "stopped"):
        provider = value.get("provider")
        if isinstance(provider, str) and PROVIDER.fullmatch(provider):
            print("Có thể tiếp tục thủ công: exec --provider {} --resume {}".format(provider, args.run))
        else:
            print("Kiểm tra provider trước khi tiếp tục run {}".format(args.run))
    elif value.get("status") == "needs_human":
        print("Cần người kiểm tra trước khi quyết định tiếp tục; không tự giao lại.")
    elif value.get("status") == "rate_limited":
        print("Provider giới hạn lượt; không tự giao lại.")
    else:
        print("Kiểm tra kết quả: result {}".format(args.run))
    return response.returncode


def result_run(args):
    binary = wchat_binary()
    value, rc = fetch(binary, "result", args.run)
    if rc:
        return rc
    print("Trạng thái: {} (run {})".format(value.get("status"), value.get("run")))
    git = value.get("git") if isinstance(value.get("git"), dict) else {}
    print("Commit:")
    commits = git.get("commits")
    if git.get("available") is True and isinstance(commits, list):
        if commits:
            for item in commits:
                if isinstance(item, dict):
                    print("  {} {}".format(item.get("sha"), item.get("subject")))
        else:
            print("  không có commit")
    else:
        print("  không xác định: {}".format(git.get("error") or "không có bằng chứng Git"))
    if git.get("bounded") is False:
        print("  chưa có ranh giới cuối (bounded: false)")
    print("Lệnh shell:")
    shell = value.get("shell")
    if isinstance(shell, list) and shell:
        for item in shell:
            if not isinstance(item, dict):
                print("  không xác định: bản ghi không hợp lệ")
                continue
            code = item.get("exit")
            state = item.get("status")
            if code is None:
                print("  {}: exit: null; trạng thái: {}".format(item.get("cmd"), state or "không xác định"))
            else:
                print("  {}: exit: {}; trạng thái: {}".format(item.get("cmd"), code, state))
    else:
        print("  không có bản ghi lệnh shell")
    print("Câu trả lời cuối:")
    print(value.get("answer") if value.get("answer") is not None else "không có câu trả lời cuối")
    if value.get("error"):
        print("Lỗi được ghi: " + str(value["error"]))
    return 0


def cancel_run(args):
    binary = wchat_binary()
    try:
        response = invoke(binary, "run", "stop", args.run, "--json")
    except OSError as exc:
        return error("không chạy được wchat: " + str(exc))
    if response.returncode:
        if b"stop unconfirmed" in response.stderr.lower():
            output(response.stderr, sys.stderr)
            print("Stop chưa xác nhận; không suy diễn trạng thái run {}".format(args.run))
        else:
            output(response.stderr, sys.stderr)
        return response.returncode
    value, problem = parse_json(response.stdout)
    if problem:
        return error(problem)
    print("Run: {}\nTrạng thái sau stop: {}".format(value.get("run"), value.get("status")))
    return 0


def setup_run(_args):
    try:
        binary = wchat_binary()
    except WchatUnavailable as exc:
        return error(str(exc))
    try:
        version = invoke(binary, "--version")
    except OSError as exc:
        return error("chưa cài wchat: " + str(exc))
    if version.returncode:
        output(version.stderr, sys.stderr)
        return version.returncode
    found = VERSION.search(version.stdout.decode("utf-8", "replace"))
    if not found:
        return error("không đọc được phiên bản wchat; cần wchat ≥ 0.7.0 có wchat run")
    if tuple(map(int, found.groups())) < (0, 7, 0):
        return error("cần wchat ≥ 0.7.0 có wchat run; hiện tại: " + found.group(0))
    try:
        doctor = invoke(binary, "doctor")
    except OSError as exc:
        return error("không chạy được wchat doctor: " + str(exc))
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
