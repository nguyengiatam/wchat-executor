"""Contract tests: an isolated, recording wchat executable, never a real provider."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wchat_executor.py"
FAKE = r'''#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path
import sys
import time
argv = sys.argv[1:]
key = argv[1] if argv and argv[0] == "run" else ("version" if argv == ["--version"] else "doctor")
capture = Path(os.environ["FAKE_CAPTURE"])
previous = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
number = sum(row["key"] == "start" for row in previous)
stdin = sys.stdin.buffer.read() if key == "start" else b""
with capture.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"key": key, "argv": argv, "pid": os.getpid(), "stdin": base64.b64encode(stdin).decode("ascii")}) + "\n")
scenario = json.loads(os.environ.get("FAKE_SCENARIO", "{}"))
response = scenario.get(key, {})
if key == "start" and scenario.get("start_ids"):
    response = dict(response, out={"schema": 1, "run": scenario["start_ids"][number]})
defaults = {
    "start": {"schema": 1, "run": "r123"},
    "status": {"schema": 1, "run": "r123", "provider": "chatgpt", "status": "running"},
    "list": {"schema": 1, "runs": []},
    "wait": {"schema": 1, "run": "r123", "status": "done", "provider": "chatgpt"},
    "result": {"schema": 1, "run": "r123", "status": "done", "git": {"available": True, "commits": [], "bounded": True}, "shell": [], "answer": "OK"},
    "stop": {"schema": 1, "run": "r123", "status": "stopped"},
    "version": "wchat 0.7.0\n", "doctor": "doctor OK\n",
}
if response.get("sleep"):
    time.sleep(response["sleep"])
out = response.get("out", defaults[key])
sys.stdout.write(out if isinstance(out, str) else json.dumps(out))
sys.stderr.write(response.get("err", ""))
sys.exit(response.get("code", 0))
'''


class ExecutorContract(unittest.TestCase):
    def setUp(self):
        # Temp cleanup is explicitly confined to the approved resolved TMPDIR.
        self.base = Path(os.environ.get("TMPDIR", "/private/tmp")).resolve()
        if not self.base.is_dir():
            raise RuntimeError("safe temporary base unavailable: " + str(self.base))
        self.temp = tempfile.TemporaryDirectory(prefix="wchat-p1-", dir=str(self.base))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        if not str(self.root).startswith(str(self.base) + os.sep):
            raise RuntimeError("unsafe temporary path: " + str(self.root))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.other = self.root / "repo-other"
        self.other.mkdir()
        self.binary = self.root / "wchat-fake"
        self.binary.write_text(FAKE, encoding="utf-8")
        self.binary.chmod(0o755)
        self.capture = self.root / "calls.jsonl"
        self.env = os.environ.copy()
        self.env.update(WCHAT_BIN=str(self.binary), FAKE_CAPTURE=str(self.capture), FAKE_SCENARIO="{}")
        self.task = self.root / "task.txt"
        self.task.write_bytes(b"Do one thing.\n")

    def scenario(self, **actions):
        self.env["FAKE_SCENARIO"] = json.dumps(actions)

    def call(self, *args, cwd=None, env=None, script=SCRIPT):
        return subprocess.run([sys.executable, str(script), *args], cwd=str(cwd or self.repo),
                              env=env or self.env, capture_output=True, text=True, timeout=15)

    def exec_task(self, *extra, cwd=None):
        return self.call("exec", "--provider", "chatgpt", "--task-file", str(self.task),
                         *extra, cwd=cwd)

    def captures(self, key=None):
        entries = [json.loads(line) for line in self.capture.read_text().splitlines()] if self.capture.exists() else []
        return [entry for entry in entries if entry["key"] == key] if key else entries

    def test_missing_provider_rejected_without_calling_wchat(self):
        p = self.call("exec", "--task-file", str(self.task))
        self.assertEqual(2, p.returncode)
        self.assertIn("--provider", p.stderr)
        self.assertEqual([], self.captures())

    def test_provider_validation_happens_before_wchat(self):
        p = self.call("exec", "--provider", "ChatGPT;touch", "--task-file", str(self.task))
        self.assertEqual(2, p.returncode)
        self.assertEqual([], self.captures())

    def test_start_refused_preserves_stderr_and_code(self):
        self.scenario(start={"code": 2, "err": "wchat: session missing\n"})
        p = self.exec_task()
        self.assertEqual(2, p.returncode)
        self.assertEqual("wchat: session missing\n", p.stderr)
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=refused"))
        self.assertFalse(self.task.exists())
        self.assertEqual(1, len(self.captures("start")))

    def test_unconfirmed_start_is_unknown_and_not_retried(self):
        self.scenario(start={"code": 1, "err": "wchat: start unconfirmed (log elsewhere)\n"})
        p = self.exec_task()
        self.assertEqual(1, p.returncode)
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=unknown"))
        self.assertIn(str(self.repo), p.stdout)
        self.assertIn("status", p.stdout)
        self.assertEqual(1, len(self.captures("start")))

    def test_malformed_start_json_is_unknown_not_retired_or_retried(self):
        self.scenario(start={"out": "not-json", "code": 0})
        p = self.exec_task()
        self.assertEqual(1, p.returncode)
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=unknown"))
        self.assertEqual(1, len(self.captures("start")))

    def test_start_schema_two_is_unknown_with_upgrade_advice(self):
        self.scenario(start={"out": {"schema": 2, "run": "r123"}})
        p = self.exec_task()
        self.assertEqual(1, p.returncode)
        self.assertIn("cần cập nhật", p.stdout)
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=unknown"))

    def test_unknown_schema_is_rejected_before_presenting_status(self):
        self.scenario(status={"out": {"schema": 2, "run": "r123", "status": "done"}})
        p = self.call("status", "r123")
        self.assertEqual(2, p.returncode)
        self.assertIn("schema 2", p.stderr)
        self.assertIn("cần cập nhật", p.stderr)
        self.assertNotIn("Trạng thái", p.stdout)

    def test_status_filters_by_exact_realpath_without_resorting(self):
        self.scenario(list={"out": {"schema": 1, "runs": [
            {"run": "new", "status": "running", "updated": "3", "workspace": str(self.repo)},
            {"run": "foreign", "status": "done", "updated": "2", "workspace": str(self.other)},
            {"run": "old", "status": "done", "updated": "1", "workspace": str(self.repo)}]}})
        p = self.call("status")
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertEqual(["new", "old"], [line.split()[0] for line in p.stdout.splitlines()])
        self.assertEqual(["run", "list", "--json"], self.captures("list")[0]["argv"])

    def test_status_null_and_malformed_workspace_are_ignored(self):
        self.scenario(list={"out": {"schema": 1, "runs": [
            {"run": "bad", "workspace": None}, {"run": "bad2", "workspace": 9},
            {"run": "valid", "workspace": str(self.repo), "status": "running"}]}})
        p = self.call("status")
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn("valid", p.stdout)
        self.assertNotIn("bad", p.stdout)

    def test_status_single_run_uses_status_endpoint(self):
        p = self.call("status", "r123")
        self.assertEqual(0, p.returncode)
        self.assertIn("Trạng thái: running", p.stdout)
        self.assertEqual(["run", "status", "r123", "--json"], self.captures()[0]["argv"])

    def test_cancel_preserves_each_authoritative_status(self):
        for state in ("stopped", "needs_human", "done"):
            with self.subTest(state=state):
                self.scenario(stop={"out": {"schema": 1, "run": "r123", "status": state}})
                p = self.call("cancel", "r123")
                self.assertEqual(0, p.returncode, p.stderr)
                self.assertIn("Trạng thái sau stop: " + state, p.stdout)

    def test_cancel_unconfirmed_only_for_specific_diagnostic(self):
        self.scenario(stop={"code": 1, "err": "wchat: stop unconfirmed for run r123\n"})
        p = self.call("cancel", "r123")
        self.assertEqual(1, p.returncode)
        self.assertIn("Stop chưa xác nhận", p.stdout)
        self.assertIn("stop unconfirmed", p.stderr)

    def test_cancel_pid_mismatch_preserves_error_not_unconfirmed(self):
        self.scenario(stop={"code": 1, "err": "wchat: held by pid 222 but record names pid 111\n"})
        p = self.call("cancel", "r123")
        self.assertEqual(1, p.returncode)
        self.assertEqual("wchat: held by pid 222 but record names pid 111\n", p.stderr)
        self.assertNotIn("chưa xác nhận", p.stdout.lower())

    def test_setup_missing_wchat(self):
        self.env["WCHAT_BIN"] = str(self.root / "nonexistent")
        p = self.call("setup")
        self.assertEqual(2, p.returncode)
        self.assertIn("WCHAT_BIN", p.stderr)
        self.assertEqual([], self.captures())

    def test_setup_absent_wchat_in_path(self):
        self.env.pop("WCHAT_BIN")
        self.env["PATH"] = str(self.root)
        p = self.call("setup")
        self.assertEqual(2, p.returncode)
        self.assertIn("chưa cài wchat", p.stderr)
        self.assertEqual([], self.captures())

    def test_setup_old_version(self):
        self.scenario(version={"out": "wchat 0.6.0\n"})
        p = self.call("setup")
        self.assertEqual(2, p.returncode)
        self.assertIn("≥ 0.7.0", p.stderr)
        self.assertEqual([], self.captures("doctor"))

    def test_setup_doctor_error_preserved(self):
        self.scenario(doctor={"code": 1, "err": "wchat: config malformed\n"})
        p = self.call("setup")
        self.assertEqual(1, p.returncode)
        self.assertEqual("wchat: config malformed\n", p.stderr)
        self.assertNotIn("browser", p.stderr.lower())

    def test_setup_success(self):
        p = self.call("setup")
        self.assertEqual(0, p.returncode)
        self.assertIn("doctor OK", p.stdout)
        self.assertEqual(["version", "doctor"], [item["key"] for item in self.captures()])

    def test_wait_reports_all_terminal_states_and_exit_codes(self):
        for state, code in (("done", 0), ("needs_human", 4), ("rate_limited", 6),
                            ("stopped", 5), ("died", 1)):
            with self.subTest(state=state):
                self.scenario(wait={"code": code, "out": {"schema": 1, "run": "r123", "status": state}})
                p = self.call("wait", "r123")
                self.assertEqual(code, p.returncode)
                self.assertIn("Trạng thái: " + state, p.stdout)
                self.assertIn("Mã thoát: " + str(code), p.stdout)

    def test_wait_timeout_seven_is_still_running(self):
        self.scenario(wait={"code": 7, "out": {"schema": 1, "run": "r123", "status": "running"}})
        p = self.call("wait", "r123")
        self.assertEqual(7, p.returncode)
        self.assertIn("Mã thoát: 7", p.stdout)
        self.assertIn("Vẫn đang chạy", p.stdout)
        self.assertNotIn("result r123", p.stdout)

    def test_wait_forwards_timeout_and_returns_underlying_code(self):
        self.scenario(wait={"code": 7, "out": {"schema": 1, "run": "r123", "status": "running"}})
        p = self.call("wait", "r123", "--timeout", "1")
        self.assertEqual(7, p.returncode)
        self.assertEqual(["run", "wait", "r123", "--json", "--timeout", "1"], self.captures()[0]["argv"])

    def test_result_preserves_four_evidence_groups(self):
        self.scenario(result={"out": {"schema": 1, "run": "r123", "status": "done",
            "git": {"available": True, "bounded": True, "commits": [{"sha": "a" * 40, "subject": "Do work"}]},
            "shell": [{"cmd": "echo yay", "exit": 0, "status": "exited"}], "answer": "Job finished"}})
        p = self.call("result", "r123")
        self.assertEqual(0, p.returncode, p.stderr)
        for required in ("Trạng thái: done", "Commit:", "a" * 40, "Do work",
                         "Lệnh shell:", "echo yay", "exit: 0", "Câu trả lời cuối:", "Job finished"):
            self.assertIn(required, p.stdout)

    def test_result_distinguishes_no_commit_from_unavailable_evidence(self):
        self.scenario(result={"out": {"schema": 1, "run": "r123", "status": "done",
            "git": {"available": True, "commits": [], "bounded": True}, "shell": [], "answer": None}})
        p = self.call("result", "r123")
        self.assertEqual(0, p.returncode)
        self.assertIn("không có commit", p.stdout)
        self.assertNotIn("không xác định", p.stdout)

    def test_result_unavailable_git_and_uncertain_shell_are_not_success(self):
        self.scenario(result={"out": {"schema": 1, "run": "r123", "status": "died",
            "git": {"available": False, "error": "git start missing", "commits": None, "bounded": False},
            "shell": [{"cmd": "dangerous?", "exit": None, "status": "uncertain"},
                      {"cmd": "lost", "exit": None, "status": "unavailable"}], "answer": None}})
        p = self.call("result", "r123")
        self.assertEqual(0, p.returncode)
        for required in ("không xác định", "git start missing", "bounded: false", "exit: null",
                         "uncertain", "unavailable", "không có câu trả lời cuối"):
            self.assertIn(required, p.stdout)
        self.assertNotIn("không có commit", p.stdout)

    def test_resume_requires_provider(self):
        p = self.call("exec", "--resume", "r123")
        self.assertEqual(2, p.returncode)
        self.assertEqual([], self.captures())

    def test_resume_rejects_different_provider_before_start(self):
        self.scenario(status={"out": {"schema": 1, "run": "r123", "provider": "deepseek"}})
        p = self.call("exec", "--provider", "chatgpt", "--resume", "r123")
        self.assertEqual(2, p.returncode)
        self.assertIn("không khớp", p.stderr)
        self.assertEqual([], self.captures("start"))
        self.assertEqual(1, len(self.captures("status")))

    def test_resume_unknown_provider_rejected(self):
        self.scenario(status={"out": {"schema": 1, "run": "r123", "provider": None}})
        p = self.call("exec", "--provider", "chatgpt", "--resume", "r123")
        self.assertEqual(2, p.returncode)
        self.assertEqual([], self.captures("start"))

    def test_resume_matching_provider_forwards_resume_without_new_stdin(self):
        p = self.call("exec", "--provider", "chatgpt", "--resume", "r123")
        self.assertEqual(0, p.returncode, p.stderr)
        start = self.captures("start")[0]
        self.assertIn("--resume", start["argv"])
        self.assertEqual("r123", start["argv"][start["argv"].index("--resume") + 1])
        self.assertEqual(b"", base64.b64decode(start["stdin"]))

    def test_resume_and_new_task_are_mutually_exclusive(self):
        p = self.call("exec", "--provider", "chatgpt", "--task-file", str(self.task),
                      "--resume", "r123")
        self.assertEqual(2, p.returncode)
        self.assertEqual([], self.captures())
        self.assertTrue(self.task.exists())

    def test_multiline_task_is_byte_exact_stdin_and_not_executed(self):
        marker = self.root / "PWNED"
        payload = ("Line 1 with ' and \" and ;\n" + "$(touch " + str(marker) + ")\n" +
                   "Unicode: tiếng Việt 🧪\n").encode("utf-8")
        self.task.write_bytes(payload)
        p = self.exec_task()
        self.assertEqual(0, p.returncode, p.stderr)
        record = self.captures("start")[0]
        self.assertEqual(payload, base64.b64decode(record["stdin"]))
        self.assertNotIn("touch", " ".join(record["argv"]))
        self.assertFalse(marker.exists())

    def test_agent_flags_precede_plugin_flags_and_task_remains_stdin(self):
        p = self.exec_task("--", "--max-rounds", "5", "--session", "s", "--new")
        self.assertEqual(0, p.returncode, p.stderr)
        record = self.captures("start")[0]
        argv = record["argv"]
        self.assertEqual(["run", "start", "--max-rounds", "5", "--session", "s", "--new"], argv[:7])
        self.assertEqual("chatgpt", argv[argv.index("--provider") + 1])
        self.assertEqual(b"Do one thing.\n", base64.b64decode(record["stdin"]))
        self.assertEqual("--json", argv[-1])

    def test_workspace_defaults_to_caller_cwd_even_when_script_elsewhere(self):
        unicode_repo = self.root / "project has spaces tiếng Việt"
        unicode_repo.mkdir()
        p = self.exec_task(cwd=unicode_repo)
        self.assertEqual(0, p.returncode, p.stderr)
        argv = self.captures("start")[0]["argv"]
        self.assertEqual(str(unicode_repo), argv[argv.index("--workspace") + 1])
        self.assertNotEqual(str(SCRIPT.parent), str(unicode_repo))

    def test_explicit_workspace_is_absolute(self):
        p = self.exec_task("--workspace", "../repo-other")
        self.assertEqual(0, p.returncode)
        argv = self.captures("start")[0]["argv"]
        self.assertEqual(str(self.other), argv[argv.index("--workspace") + 1])

    def test_explicit_broken_wchat_bin_never_falls_back_to_path(self):
        fake_path = self.root / "fallback"
        fake_path.mkdir()
        (fake_path / "wchat").write_text(FAKE, encoding="utf-8")
        (fake_path / "wchat").chmod(0o755)
        self.env["PATH"] = str(fake_path) + os.pathsep + self.env.get("PATH", "")
        self.env["WCHAT_BIN"] = str(self.root / "missing-bin")
        p = self.exec_task()
        self.assertEqual(2, p.returncode)
        self.assertIn("refusing PATH fallback", p.stderr)
        self.assertEqual([], self.captures())

    def test_start_removes_task_file_on_success(self):
        p = self.exec_task()
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertFalse(self.task.exists())
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=created RUN=r123"))

    def test_start_stderr_warning_is_not_parsed_as_json(self):
        self.scenario(start={"err": "wchat: unverified-provider warning\n"})
        p = self.exec_task()
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn("unverified-provider warning", p.stderr)
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=created RUN=r123"))

    def test_stdout_prefix_warning_makes_start_result_unknown(self):
        self.scenario(start={"out": "warning\n{\"schema\": 1, \"run\": \"r123\"}\n"})
        p = self.exec_task()
        self.assertEqual(1, p.returncode)
        self.assertTrue(p.stdout.rstrip().endswith("WCHAT_START=unknown"))

    def test_two_immediate_execs_are_distinct_and_visible_in_status(self):
        self.scenario(start_ids=["r1", "r2"], list={"out": {"schema": 1, "runs": [
            {"run": "r2", "status": "running", "workspace": str(self.repo)},
            {"run": "r1", "status": "running", "workspace": str(self.repo)}]}})
        a = self.exec_task()
        self.task.write_bytes(b"Next task\n")
        b = self.exec_task()
        status = self.call("status")
        self.assertEqual([0, 0, 0], [a.returncode, b.returncode, status.returncode])
        self.assertIn("WCHAT_START=created RUN=r1", a.stdout)
        self.assertIn("WCHAT_START=created RUN=r2", b.stdout)
        self.assertEqual(["r2", "r1"], [line.split()[0] for line in status.stdout.splitlines()])
        self.assertEqual(2, len(self.captures("start")))

    def test_interrupting_wait_reaps_reader_without_touching_run_state(self):
        self.scenario(wait={"sleep": 10})
        checkpoint = self.root / "run-record.json"
        checkpoint.write_text('{"status":"running"}', encoding="utf-8")
        child = subprocess.Popen([sys.executable, str(SCRIPT), "wait", "r123"],
                                 cwd=str(self.repo), env=self.env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        reader_pid = None
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                recorded = self.captures("wait")
                if recorded:
                    reader_pid = recorded[0]["pid"]
                    break
                time.sleep(0.02)
            self.assertIsNotNone(reader_pid, "wait did not spawn its reader")
            child.terminate()
            child.communicate(timeout=5)
            self.assertEqual(143, child.returncode)
            with self.assertRaises(ProcessLookupError):
                os.kill(reader_pid, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
        self.assertEqual('{"status":"running"}', checkpoint.read_text(encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
