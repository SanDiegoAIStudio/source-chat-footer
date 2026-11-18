import os
import re
import subprocess
import tempfile
import shutil
import unittest

from _common import ROOT

DEMO = os.path.join(ROOT, "examples", "demo.sh")


def readme_block():
    """The fenced block under '## What you get' in the README."""
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    section = text.split("## What you get\n", 1)[1]
    match = re.search(r"```\n(.*?)\n```", section, re.S)
    return match.group(1)


class DemoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="scf-demo-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tmpdir = os.path.join(self.tmp, "tmpdir")
        self.fake_home = os.path.join(self.tmp, "home")
        os.makedirs(self.tmpdir)
        os.makedirs(self.fake_home)

    def run_demo(self):
        env = dict(os.environ)
        for key in ("CLAUDE_CONFIG_DIR", "SOURCE_CHAT_STATE_DIR", "XDG_CACHE_HOME"):
            env.pop(key, None)
        env.update(TMPDIR=self.tmpdir, HOME=self.fake_home, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(["bash", DEMO], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, cwd=self.tmp)

    def test_demo_exits_zero(self):
        proc = self.run_demo()
        self.assertEqual(proc.returncode, 0, proc.stdout.decode() + proc.stderr.decode())
        self.assertEqual(proc.stderr, b"")

    def test_output_equals_the_readme_block(self):
        out = self.run_demo().stdout.decode("utf-8")
        self.assertEqual(out.rstrip("\n"), readme_block())

    def test_two_runs_print_the_same_bytes(self):
        self.assertEqual(self.run_demo().stdout, self.run_demo().stdout)

    def test_temporary_folder_is_gone_and_home_stays_empty(self):
        proc = self.run_demo()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(os.listdir(self.tmpdir), [])
        self.assertEqual(os.listdir(self.fake_home), [])

    def test_output_holds_no_real_paths(self):
        out = self.run_demo().stdout.decode("utf-8")
        self.assertNotIn(self.tmp, out)
        self.assertNotIn(ROOT, out)
        self.assertIn("/tmp/demo/", out)
        self.assertIn("REPO/source_chat_footer.py", out)

    def test_each_command_ran(self):
        out = self.run_demo().stdout.decode("utf-8")
        for needle in ("added /tmp/demo/site/report.html", "(no output)", "dry run: nothing was changed",
                       "applied: the footers above were written", "removed /tmp/demo/site/notes.html",
                       "<!-- no-source-chat -->"):
            self.assertIn(needle, out)


if __name__ == "__main__":
    unittest.main()
