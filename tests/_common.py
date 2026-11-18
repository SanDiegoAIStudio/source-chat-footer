"""Shared helpers for the tests.

Every test builds its own temporary folders and points HOME, CLAUDE_CONFIG_DIR
and SOURCE_CHAT_STATE_DIR into them, so nothing outside the temporary folder is
read or written. Session ids, project names and pages are invented.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "source_chat_footer.py")

S1 = "aaaaaaaa-1111-4222-8333-000000000001"
S2 = "bbbbbbbb-1111-4222-8333-000000000002"
S3 = "cccccccc-1111-4222-8333-000000000003"

PLAIN = "<html><body><p>hi</p>\n</body></html>\n"
TOKEN_LEFT_RE = re.compile(r"__[A-Z][A-Z_]*__")


def epoch(year, month, day, hour=12):
    """Local-time epoch seconds, so a local date is the same on any machine."""
    return time.mktime((year, month, day, hour, 0, 0, 0, 0, -1))


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="scf-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.config = os.path.join(self.home, ".claude")
        self.projects = os.path.join(self.config, "projects")
        self.state = os.path.join(self.tmp, "state")
        self.docs = os.path.join(self.tmp, "docs")
        os.makedirs(self.projects)
        os.makedirs(self.docs)

    # -- running the tool ---------------------------------------------------

    def env(self, **over):
        env = dict(os.environ)
        for key in ("CLAUDE_CONFIG_DIR", "SOURCE_CHAT_STATE_DIR", "XDG_CACHE_HOME"):
            env.pop(key, None)
        env.update(HOME=self.home, CLAUDE_CONFIG_DIR=self.config,
                   SOURCE_CHAT_STATE_DIR=self.state, PYTHONDONTWRITEBYTECODE="1")
        for key, value in over.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run_tool(self, *args, stdin=None, env=None, tool=None):
        if stdin is None:
            stdin = b""
        elif isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        proc = subprocess.run(
            [sys.executable, tool or TOOL] + list(args),
            input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env or self.env(), cwd=self.tmp)
        proc.out = proc.stdout.decode("utf-8")
        proc.err = proc.stderr.decode("utf-8")
        return proc

    # -- building fixtures --------------------------------------------------

    def page(self, rel, text=PLAIN, mtime=None):
        path = write(os.path.join(self.docs, rel), text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def transcript(self, session, lines=None, project="proj-a", mtime=None):
        path = os.path.join(self.projects, project, session + ".jsonl")
        return self.transcript_at(path, lines, mtime)

    def transcript_at(self, path, lines=None, mtime=None):
        out = []
        for line in lines if lines is not None else [{"type": "user"}]:
            out.append(line if isinstance(line, (str, bytes)) else json.dumps(line))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = b"\n".join(x if isinstance(x, bytes) else x.encode("utf-8") for x in out) + b"\n"
        write(path, data)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    # -- the hook -----------------------------------------------------------

    def hook_input(self, session, path, transcript=None, response_path=None, **extra):
        obj = {"session_id": session, "hook_event_name": "PostToolUse", "tool_name": "Write"}
        if path is not None:
            obj["tool_input"] = {"file_path": path}
        if response_path is not None:
            obj["tool_response"] = {"filePath": response_path}
        if transcript is not None:
            obj["transcript_path"] = transcript
        obj.update(extra)
        return obj

    def hook(self, obj, *args, env=None):
        stdin = obj if isinstance(obj, (str, bytes)) else json.dumps(obj)
        return self.run_tool("hook", *args, stdin=stdin, env=env)

    def hook_json(self, proc):
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertEqual(proc.err, "")
        return json.loads(proc.out)

    def command_from(self, reminder):
        """The printed add command, split the way a shell would."""
        text = reminder["hookSpecificOutput"]["additionalContext"]
        for line in text.splitlines():
            if line.startswith(shlex.quote(sys.executable)):
                parts = shlex.split(line)
                if len(parts) > 2 and parts[2] == "add":
                    return parts
        self.fail("no add command in the reminder:\n" + text)

    # -- reading results ----------------------------------------------------

    def blocks(self, data):
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        return text.count("<!-- source-chat-footer:start -->")

    def tree_state(self, folder):
        """Bytes and modification time of every file below a folder."""
        state = {}
        for base, _dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(base, name)
                if os.path.islink(path):
                    continue
                st = os.stat(path)
                state[path] = (read(path), st.st_mtime_ns)
        return state

    def skip_if_root(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("file permissions do not stop root")
