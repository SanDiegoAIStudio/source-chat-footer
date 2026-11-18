import json
import os
import shlex
import sys
import unittest

import _common
from _common import Base, PLAIN, S1, S2, read, write

sys.dont_write_bytecode = True
sys.path.insert(0, _common.ROOT)
import source_chat_footer as scf  # noqa: E402  (only for the list of skipped names)


class HookCase(Base):
    def setUp(self):
        super().setUp()
        self.trace = self.transcript(S1)

    def run_hook(self, path, session=S1, *args, **fields):
        return self.hook(self.hook_input(session, path, **fields), *args)

    def silent(self, proc):
        self.assertEqual((proc.returncode, proc.out, proc.err), (0, "", ""))

    def reminds(self, proc):
        data = self.hook_json(proc)
        self.assertIn("hookSpecificOutput", data)
        return data

    def control(self):
        """A plain page that must be reminded: proves the hook is doing its job."""
        path = self.page("control-%d.html" % len(os.listdir(self.docs)))
        return self.reminds(self.run_hook(path))


class SilentCases(HookCase):
    def test_empty_stdin(self):
        self.control()
        self.silent(self.hook(""))
        self.silent(self.hook("   \n"))

    def test_not_json(self):
        self.control()
        self.silent(self.hook("this is not json"))
        self.silent(self.hook(b"\xff\xfe{"))

    def test_json_that_is_not_an_object(self):
        self.control()
        for text in ("[1, 2]", '"text"', "7", "null"):
            self.silent(self.hook(text))

    def test_no_session_id(self):
        path = self.page("a.html")
        self.control()
        self.silent(self.hook({"tool_input": {"file_path": path}}))

    def test_invalid_session_id(self):
        path = self.page("a.html")
        self.control()
        for bad in ("../x", "-start", "", 7, None, "a b", "x" * 129, S1 + "\n"):
            self.silent(self.run_hook(path, session=bad))

    def test_no_file_path(self):
        self.control()
        self.silent(self.hook({"session_id": S1}))
        self.silent(self.hook({"session_id": S1, "tool_input": {"file_path": ""}}))
        self.silent(self.hook({"session_id": S1, "tool_input": "text", "tool_response": "text"}))
        self.silent(self.hook({"session_id": S1, "tool_input": {"file_path": 5}}))

    def test_path_is_not_an_existing_page(self):
        self.control()
        self.silent(self.run_hook(os.path.join(self.docs, "missing.html")))
        os.makedirs(os.path.join(self.docs, "folder.html"))
        self.silent(self.run_hook(os.path.join(self.docs, "folder.html")))

    def test_non_html_file(self):
        self.control()
        path = self.page("notes.txt")
        self.silent(self.run_hook(path))
        self.silent(self.run_hook(self.page("page.html.bak")))

    def test_htm_and_upper_case_names_are_pages(self):
        self.reminds(self.run_hook(self.page("old.htm")))
        self.reminds(self.run_hook(self.page("LOUD.HTML")))

    def test_every_skipped_folder_name(self):
        self.control()
        for name in sorted(scf.SKIP_DIRS):
            with self.subTest(name=name):
                self.silent(self.run_hook(self.page(os.path.join(name, "deep", "p.html"))))

    def test_skip_list_content(self):
        expected = set("""node_modules .next dist build out coverage .git public src app pages
            components .vercel _site deploy .venv venv site-packages .tox vendor .cache
            worktrees""".split())
        self.assertEqual(set(scf.SKIP_DIRS), expected)

    def test_skip_dir_option(self):
        path = self.page(os.path.join("handout", "p.html"))
        self.reminds(self.run_hook(path))
        path2 = self.page(os.path.join("handout", "q.html"))
        self.silent(self.run_hook(path2, S1, "--skip-dir", "handout"))
        path3 = self.page(os.path.join("other", "r.html"))
        self.silent(self.hook(self.hook_input(S1, path3), "--skip-dir", "x", "--skip-dir", "other"))

    def test_opt_out_file_in_the_folder_or_above(self):
        self.control()
        write(os.path.join(self.docs, "quiet", ".no-source-chat"), "")
        self.silent(self.run_hook(self.page(os.path.join("quiet", "p.html"))))
        self.silent(self.run_hook(self.page(os.path.join("quiet", "a", "b", "p.html"))))
        self.reminds(self.run_hook(self.page(os.path.join("loud", "p.html"))))

    def test_opt_out_comment(self):
        self.control()
        path = self.page("p.html", "<html><!-- no-source-chat --><body></body></html>")
        self.silent(self.run_hook(path))

    def test_page_that_is_not_utf8(self):
        self.control()
        path = self.page("p.html", b"<html>\xff\xfe caf\xe9</html>")
        self.silent(self.run_hook(path))

    def test_template_page(self):
        self.control()
        path = self.page("p.html", "<html><body>__SESSION_ID__</body></html>")
        self.silent(self.run_hook(path))

    def test_page_that_holds_the_session_id(self):
        self.control()
        path = self.page("p.html", "<html><body>made by %s</body></html>" % S1)
        self.silent(self.run_hook(path))

    def test_marker_stops_a_second_reminder(self):
        path = self.page("p.html")
        self.reminds(self.run_hook(path))
        self.silent(self.run_hook(path))


class Reminders(HookCase):
    def test_json_shape(self):
        path = self.page("report.html")
        data = self.reminds(self.run_hook(path))
        self.assertEqual(set(data), {"hookSpecificOutput", "systemMessage"})
        out = data["hookSpecificOutput"]
        self.assertEqual(set(out), {"hookEventName", "additionalContext"})
        self.assertEqual(out["hookEventName"], "PostToolUse")
        self.assertEqual(
            data["systemMessage"],
            "source-chat-footer: report.html has no source-chat footer; asked the session to add one")

    def test_text_content_and_order(self):
        path = self.page("report.html")
        text = self.reminds(self.run_hook(path))["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("SOURCE-CHAT FOOTER MISSING: %s\n" % path))
        text.encode("ascii")
        self.assertLess(len(text), 2000 + 3 * len(path) + len(self.trace))
        marks = [
            "does not link the Claude Code session that wrote it",
            "for the user's own use",
            shlex.quote(sys.executable),
            "claude --resume",
            "Do NOT add the footer to a page that will be published, sent or handed to someone else",
            "path inside the home folder of this machine",
            ".no-source-chat",
        ]
        positions = [text.find(m) for m in marks]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        lines = text.splitlines()
        command = [x for x in lines if x.startswith(shlex.quote(sys.executable))]
        self.assertEqual(len(command), 1)
        self.assertEqual(shlex.split(command[0]), [
            sys.executable, os.path.abspath(_common.TOOL), "add", path,
            "--session", S1, "--transcript", self.trace])

    def test_out_of_date_wording(self):
        path = self.page("p.html", PLAIN)
        self.assertEqual(self.run_tool("add", path, "--session", S2,
                                       "--transcript", self.transcript(S2)).returncode, 0)
        data = self.reminds(self.run_hook(path))
        text = data["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("SOURCE-CHAT FOOTER OUT OF DATE: %s\n" % path))
        self.assertIn("names an earlier session", text)
        self.assertIn("replaces", text.splitlines()[1])

    def test_missing_wording_has_no_earlier_session_sentence(self):
        text = self.reminds(self.run_hook(self.page("p.html")))["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("earlier session", text)

    def test_quiet_drops_only_the_routine_message(self):
        path = self.page("p.html")
        data = self.hook_json(self.run_hook(path, S1, "--quiet"))
        self.assertEqual(set(data), {"hookSpecificOutput"})
        self.assertIn("SOURCE-CHAT FOOTER MISSING", data["hookSpecificOutput"]["additionalContext"])

    def test_quiet_keeps_the_no_transcript_message(self):
        path = self.page("p.html")
        proc = self.run_hook(path, "dddddddd-0000-4000-8000-00000000000d", "--quiet")
        self.assertIn("no transcript found", self.hook_json(proc)["systemMessage"])

    def test_once_per_page_per_session(self):
        path = self.page("p.html")
        other_page = self.page("q.html")
        self.transcript(S2)
        self.reminds(self.run_hook(path))
        self.silent(self.run_hook(path))
        self.reminds(self.run_hook(path, S2))
        self.reminds(self.run_hook(other_page))
        self.silent(self.run_hook(other_page))
        self.assertEqual(len(os.listdir(self.state)), 3)

    def test_marker_is_an_empty_file_named_by_a_hash(self):
        path = self.page("p.html")
        self.reminds(self.run_hook(path))
        names = os.listdir(self.state)
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r"^[0-9a-f]{40}$")
        self.assertEqual(os.path.getsize(os.path.join(self.state, names[0])), 0)
        import hashlib
        want = hashlib.sha256(("%s|%s" % (S1, path)).encode()).hexdigest()[:40]
        self.assertEqual(names[0], want)

    def test_file_path_comes_from_tool_input_first(self):
        a = self.page("a.html")
        b = self.page("b.html")
        data = self.reminds(self.run_hook(a, response_path=b))
        self.assertIn("MISSING: %s\n" % a, data["hookSpecificOutput"]["additionalContext"])

    def test_file_path_falls_back_to_tool_response(self):
        b = self.page("b.html")
        data = self.reminds(self.run_hook(None, response_path=b))
        self.assertIn("MISSING: %s\n" % b, data["hookSpecificOutput"]["additionalContext"])
        data = self.reminds(self.hook({"session_id": S1, "tool_input": {"file_path": ""},
                                       "tool_response": {"filePath": self.page("c.html")}}))
        self.assertIn("c.html", data["hookSpecificOutput"]["additionalContext"])

    def test_symlinked_page_is_reported_by_its_real_path(self):
        real = self.page("real.html")
        link = os.path.join(self.docs, "link.html")
        os.symlink(real, link)
        text = self.reminds(self.run_hook(link))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MISSING: %s\n" % real, text)

    def test_printed_command_runs_end_to_end(self):
        path = self.page(os.path.join("my pages", "it's here", "report.html"))
        data = self.reminds(self.run_hook(path))
        parts = self.command_from(data)
        self.assertEqual(parts[3], path)
        done = _common.subprocess.run(parts, env=self.env(), capture_output=True, cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        text = read(path).decode()
        self.assertIn('data-source-chat="%s"' % S1, text)
        self.assertEqual(self.blocks(text), 1)
        self.silent(self.run_hook(path))
        self.silent(self.run_hook(path, S1, "--quiet"))

    def test_printed_command_quotes_every_argument(self):
        path = self.page(os.path.join("a b", "c$d.html"))
        text = self.reminds(self.run_hook(path))["hookSpecificOutput"]["additionalContext"]
        self.assertIn(shlex.quote(path), text)
        self.assertNotIn(" %s " % path, text)


class TranscriptLookup(HookCase):
    def command(self, proc):
        return self.command_from(self.reminds(proc))

    def test_hint_wins_when_named_for_the_session(self):
        other = self.transcript(S1, project="proj-b", mtime=2000000000)
        hint = self.transcript(S1, project="proj-c", mtime=1000000000)
        parts = self.command(self.run_hook(self.page("p.html"), transcript_path=hint))
        self.assertEqual(parts[-1], hint)
        self.assertNotEqual(parts[-1], other)

    def test_newest_file_in_the_projects_folder_wins(self):
        self.transcript(S1, project="proj-b", mtime=1000000000)
        newest = self.transcript(S1, project="proj-c", mtime=1500000000)
        self.transcript(S1, project="proj-d", mtime=1100000000)
        os.utime(self.trace, (900000000, 900000000))
        parts = self.command(self.run_hook(self.page("p.html")))
        self.assertEqual(parts[-1], newest)

    def test_equal_times_are_broken_by_path(self):
        for project in ("proj-z", "proj-m", "proj-b"):
            self.transcript(S1, project=project, mtime=1200000000)
        os.utime(self.trace, (1200000000, 1200000000))
        parts = self.command(self.run_hook(self.page("p.html")))
        self.assertEqual(parts[-1], os.path.join(self.projects, "proj-a", S1 + ".jsonl"))

    def test_hint_with_another_name_loses_to_the_projects_folder(self):
        hint = write(os.path.join(self.tmp, "elsewhere", "other.jsonl"), "{}\n")
        parts = self.command(self.run_hook(self.page("p.html"), transcript_path=hint))
        self.assertEqual(parts[-1], self.trace)

    def test_hint_with_another_name_is_the_last_resort(self):
        session = "eeeeeeee-0000-4000-8000-00000000000e"
        hint = write(os.path.join(self.tmp, "elsewhere", "other.jsonl"), "{}\n")
        parts = self.command(self.run_hook(self.page("p.html"), session, transcript_path=hint))
        self.assertEqual(parts[-1], hint)

    def test_nothing_found_writes_no_marker(self):
        session = "dddddddd-0000-4000-8000-00000000000d"
        path = self.page("p.html")
        for _ in range(2):
            proc = self.run_hook(path, session, transcript_path=os.path.join(self.tmp, "gone.jsonl"))
            data = self.hook_json(proc)
            self.assertEqual(data, {"systemMessage": (
                "source-chat-footer: no transcript found for session %s, so no footer was "
                "suggested for p.html" % session)})
        self.assertFalse(os.path.exists(self.state))

    def test_projects_path_with_glob_characters(self):
        config = os.path.join(self.tmp, "cfg[1]*")
        want = write(os.path.join(config, "projects", "proj-a", S2 + ".jsonl"), "{}\n")
        env = self.env(CLAUDE_CONFIG_DIR=config)
        proc = self.run_tool("hook", stdin=json.dumps(self.hook_input(S2, self.page("p.html"))), env=env)
        self.assertEqual(self.command(proc)[-1], want)

    def test_default_config_folder_is_inside_home(self):
        session = "ffffffff-0000-4000-8000-00000000000f"
        want = self.transcript(session)
        self.assertTrue(want.startswith(os.path.join(self.home, ".claude")))
        env = self.env(CLAUDE_CONFIG_DIR=None)
        proc = self.run_tool("hook", stdin=json.dumps(self.hook_input(session, self.page("p.html"))), env=env)
        self.assertEqual(self.command(proc)[-1], want)
        env = self.env(CLAUDE_CONFIG_DIR="")
        proc = self.run_tool("hook", stdin=json.dumps(self.hook_input(session, self.page("q.html"))), env=env)
        self.assertEqual(self.command(proc)[-1], want)


class StateFolder(HookCase):
    def test_state_folder_that_cannot_be_written(self):
        blocker = write(os.path.join(self.tmp, "blocker"), "a file")
        env = self.env(SOURCE_CHAT_STATE_DIR=os.path.join(blocker, "inside"))
        path = self.page("p.html")
        for _ in range(2):
            proc = self.run_tool("hook", stdin=json.dumps(self.hook_input(S1, path)), env=env)
            self.reminds(proc)

    def test_state_folder_from_the_cache_variable(self):
        cache = os.path.join(self.tmp, "cache")
        env = self.env(SOURCE_CHAT_STATE_DIR=None, XDG_CACHE_HOME=cache)
        proc = self.run_tool("hook", stdin=json.dumps(self.hook_input(S1, self.page("p.html"))), env=env)
        self.reminds(proc)
        self.assertEqual(len(os.listdir(os.path.join(cache, "source-chat-footer"))), 1)

    def test_state_folder_default_is_inside_home(self):
        env = self.env(SOURCE_CHAT_STATE_DIR="", XDG_CACHE_HOME="")
        proc = self.run_tool("hook", stdin=json.dumps(self.hook_input(S1, self.page("p.html"))), env=env)
        self.reminds(proc)
        self.assertEqual(len(os.listdir(os.path.join(self.home, ".cache", "source-chat-footer"))), 1)


class Failures(HookCase):
    def test_unexpected_exception_prints_one_message_and_exits_zero(self):
        self.skip_if_root()
        path = self.page("p.html")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        for extra in ((), ("--quiet",)):
            proc = self.run_hook(path, S1, *extra)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.out),
                             {"systemMessage": "source-chat-footer: hook failed: PermissionError"})
            self.assertNotIn("Traceback", proc.err)

    def test_bad_arguments_still_exit_zero(self):
        proc = self.hook(self.hook_input(S1, self.page("p.html")), "--no-such-option")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.out),
                         {"systemMessage": "source-chat-footer: hook failed: UsageError"})


if __name__ == "__main__":
    unittest.main()
