import datetime
import os
import pathlib
import re
import stat
import unittest

from _common import Base, PLAIN, S1, S2, TOKEN_LEFT_RE, read, write

START = "<!-- source-chat-footer:start -->"
END = "<!-- source-chat-footer:end -->"
TOKENS = ["__SESSION_ID__", "__TRACE_URL__", "__TRACE_PATH__", "__DATE__", "__LABEL__",
          "__CONFIDENCE__"]


class AddCase(Base):
    def setUp(self):
        super().setUp()
        self.trace = self.transcript(S1)

    def add(self, path, *extra, session=S1):
        args = ["add", path, "--session=" + session]
        if "--transcript" not in extra:
            args += ["--transcript", self.trace]
        return self.run_tool(*(args + list(extra)))

    def added(self, path, *extra, session=S1):
        proc = self.add(path, *extra, session=session)
        self.assertEqual((proc.returncode, proc.err), (0, ""), proc.err)
        return proc

    def refused(self, path, *extra, session=S1, args=None, want=None):
        before = read(path) if os.path.isfile(path) else None
        proc = self.add(path, *extra, session=session) if args is None else self.run_tool(*args)
        self.assertEqual(proc.returncode, 2, proc.out + proc.err)
        self.assertEqual(proc.out, "")
        self.assertEqual(len(proc.err.strip().splitlines()), 1, proc.err)
        self.assertNotIn("Traceback", proc.err)
        if want:
            self.assertIn(want, proc.err)
        if before is not None:
            self.assertEqual(read(path), before)
        return proc


class Placement(AddCase):
    def test_goes_before_the_last_closing_body_tag(self):
        text = "<html><body><script>var s='</body>';</script>\n<p>x</p>\n</body></html>\n"
        path = self.page("p.html", text)
        self.added(path)
        out = read(path).decode()
        at_block = out.index(START)
        self.assertGreater(at_block, out.index("<p>x</p>"))
        self.assertEqual(out.count("</body>"), 2)
        self.assertEqual(out[out.index(END) + len(END):], "\n</body></html>\n")
        self.assertEqual(out.index("var s='</body>'") < at_block, True)

    def test_upper_case_body_tag(self):
        path = self.page("p.html", "<HTML><BODY><p>x</p>\n</BODY></HTML>\n")
        self.added(path)
        out = read(path).decode()
        self.assertTrue(out.index(END) < out.index("</BODY>"))
        self.assertTrue(out.endswith("\n</BODY></HTML>\n"))

    def test_no_body_tag_goes_to_the_end(self):
        path = self.page("p.html", "<p>fragment</p>")
        self.added(path)
        out = read(path).decode()
        self.assertTrue(out.startswith("<p>fragment</p>\n" + START))
        self.assertTrue(out.endswith(END + "\n"))

    def test_empty_page(self):
        path = self.page("p.html", "")
        self.added(path)
        out = read(path).decode()
        self.assertTrue(out.startswith(START) and out.endswith(END + "\n"))

    def test_all_six_tokens_are_filled(self):
        path = self.page("p.html")
        self.added(path, "--date", "2026-01-15")
        out = read(path).decode()
        for token in TOKENS:
            self.assertNotIn(token, out)
        self.assertIsNone(TOKEN_LEFT_RE.search(out))
        self.assertIn('<footer class="source-chat" data-source-chat="%s" data-link-confidence="wrote">' % S1, out)
        self.assertIn('<span class="source-chat__label">Source chat</span>', out)
        self.assertIn("<code>claude --resume %s</code>" % S1, out)
        self.assertIn('data-copy="claude --resume %s"' % S1, out)
        self.assertIn("<span>session %s</span><span>generated 2026-01-15</span>" % S1, out)
        self.assertIn('<a href="%s">%s</a>' % (pathlib.Path(self.trace).as_uri(), self.trace), out)

    def test_output_line(self):
        path = self.page("p.html")
        self.assertEqual(self.added(path).out, "added %s %s\n" % (path, S1))
        self.assertEqual(self.added(path).out, "replaced %s %s\n" % (path, S1))

    def test_default_date_is_today(self):
        path = self.page("p.html")
        before = datetime.date.today().isoformat()
        self.added(path)
        after = datetime.date.today().isoformat()
        stamp = re.search(r"generated (\d{4}-\d{2}-\d{2})", read(path).decode()).group(1)
        self.assertIn(stamp, (before, after))

    def test_link_is_percent_encoded_for_a_path_with_a_space(self):
        trace = self.transcript(S2, project="my project")
        path = self.page("p.html")
        self.added(path, "--transcript", trace, session=S2)
        out = read(path).decode()
        self.assertIn('href="file://%s/my%%20project/%s.jsonl"' % (
            pathlib.Path(self.projects).as_uri()[len("file://"):], S2), out)
        self.assertIn(">%s</a>" % trace, out)

    def test_values_are_escaped(self):
        trace = self.transcript(S2, project='a&b"c<d>')
        path = self.page("p.html")
        self.added(path, "--transcript", trace, session=S2)
        out = read(path).decode()
        self.assertIn("a&amp;b&quot;c&lt;d&gt;", out)
        self.assertNotIn('a&b"c<d>', out)
        self.assertIn("a%26b%22c%3Cd%3E", out)

    def test_a_token_in_the_path_is_not_filled_twice(self):
        trace = self.transcript(S2, project="__DATE__")
        path = self.page("p.html")
        self.added(path, "--transcript", trace, "--date", "2026-01-15", session=S2)
        out = read(path).decode()
        self.assertIn("/__DATE__/", out)

    def test_transcript_with_another_name_is_used_when_nothing_else_exists(self):
        session = "dddddddd-0000-4000-8000-00000000000d"
        other = write(os.path.join(self.tmp, "x", "named-otherwise.jsonl"), "{}\n")
        path = self.page("p.html")
        self.added(path, "--transcript", other, session=session)
        self.assertIn(">%s</a>" % other, read(path).decode())

    def test_transcript_found_by_session_when_not_given(self):
        path = self.page("p.html")
        proc = self.run_tool("add", path, "--session", S1)
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertIn(">%s</a>" % self.trace, read(path).decode())


class Replace(AddCase):
    def test_replace_leaves_exactly_one_block_and_drops_the_old_id(self):
        path = self.page("p.html")
        self.added(path, session=S1)
        second = self.transcript(S2)
        self.added(path, "--transcript", second, session=S2)
        out = read(path).decode()
        self.assertEqual(self.blocks(out), 1)
        self.assertEqual(out.count(END), 1)
        self.assertNotIn(S1, out)
        self.assertIn(S2, out)

    def test_two_existing_blocks_become_one(self):
        path = self.page("p.html")
        self.added(path)
        text = read(path).decode()
        double = text.replace("</body>", text[text.index(START):text.index(END) + len(END)] + "\n</body>")
        write(path, double)
        self.assertEqual(self.blocks(double), 2)
        self.added(path)
        self.assertEqual(self.blocks(read(path)), 1)

    def test_running_twice_leaves_identical_bytes(self):
        for text in (PLAIN, "<p>no body</p>", "<p>no newline</p></body>", ""):
            path = self.page("p.html", text)
            self.added(path, "--date", "2026-01-15")
            first = read(path)
            self.added(path, "--date", "2026-01-15")
            self.assertEqual(read(path), first, text)

    def test_text_outside_the_block_is_unchanged(self):
        original = "\ufeff<html>\r\n<body>\r\n<p>x</p>\r\n</body>\r\n</html>\r\n"
        path = self.page("p.html", original)
        self.added(path)
        data = read(path)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf<html>\r\n"))
        start = data.index(START.encode())
        end = data.index(END.encode()) + len(END) + 1
        self.assertEqual(data[:start] + data[end:], original.encode("utf-8"))
        self.added(path)
        self.assertEqual(read(path), data)

    def test_permission_bits_are_kept(self):
        path = self.page("p.html")
        os.chmod(path, 0o640)
        self.added(path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)

    def test_no_temporary_file_is_left_behind(self):
        path = self.page("p.html")
        self.added(path)
        self.assertEqual(os.listdir(self.docs), ["p.html"])

    def test_symlinked_page_changes_the_real_file(self):
        real = self.page("real.html")
        link = os.path.join(self.docs, "link.html")
        os.symlink(real, link)
        proc = self.added(link)
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.path.realpath(link), real)
        self.assertEqual(self.blocks(read(real)), 1)
        self.assertEqual(proc.out, "added %s %s\n" % (real, S1))


class Refusals(AddCase):
    def test_not_an_existing_page(self):
        self.refused(os.path.join(self.docs, "missing.html"))
        self.refused(self.page("notes.txt"))
        os.makedirs(os.path.join(self.docs, "dir.html"))
        self.refused(os.path.join(self.docs, "dir.html"))

    def test_invalid_session_id(self):
        path = self.page("p.html")
        for bad in ("../x", "-x", "a b", "x" * 129, "a\nb", "a/b"):
            self.refused(path, session=bad, want="not a valid session id")

    def test_missing_session_option_is_a_usage_error(self):
        path = self.page("p.html")
        proc = self.run_tool("add", path)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.err)

    def test_opted_out_by_file(self):
        write(os.path.join(self.docs, "quiet", ".no-source-chat"), "")
        path = self.page(os.path.join("quiet", "deep", "p.html"))
        self.refused(path, want=os.path.join(self.docs, "quiet", ".no-source-chat"))

    def test_opted_out_by_comment(self):
        path = self.page("p.html", "<p>x</p><!-- no-source-chat -->")
        self.refused(path, want="<!-- no-source-chat -->")

    def test_not_utf8(self):
        path = self.page("p.html", b"<p>caf\xe9</p>")
        self.refused(path, want="not UTF-8")

    def test_template(self):
        path = self.page("p.html", "<p>__SESSION_ID__</p>")
        self.refused(path, want="template")

    def test_transcript_option_names_a_missing_file(self):
        path = self.page("p.html")
        self.refused(path, "--transcript", os.path.join(self.tmp, "gone.jsonl"), want="does not exist")

    def test_no_transcript_found(self):
        path = self.page("p.html")
        self.refused(path, "--transcript", os.path.join(self.tmp, "none", "x.jsonl"))
        proc = self.run_tool("add", path, "--session", "dddddddd-0000-4000-8000-00000000000d")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(read(path).decode(), PLAIN)
        self.assertIn("no transcript found", proc.err)

    def test_dates_that_are_not_real(self):
        path = self.page("p.html")
        for bad in ("2026-02-30", "2026-1-5", "tomorrow", "2026-01-15x", "2026-13-01", "15-01-2026", ""):
            self.refused(path, "--date", bad, want="--date")

    def test_start_mark_without_end_mark(self):
        for text in (START + "<p>x</p>", "<p>%s ok %s</p>%s tail" % (START, END, START)):
            path = self.page("p.html", text)
            self.refused(path, want="no end mark")

    def test_end_mark_before_start_mark_is_refused(self):
        path = self.page("p.html", END + "<p>x</p>" + START)
        self.refused(path, want="no end mark")


class TemplateRules(AddCase):
    def test_template_file_shape(self):
        text = read(os.path.join(os.path.dirname(os.path.dirname(__file__)), "footer-snippet.html")).decode()
        lines = text.rstrip("\n").split("\n")
        self.assertEqual(lines[0], START)
        self.assertEqual(lines[-1], END)
        for token in TOKENS:
            self.assertIn(token, text)
        self.assertEqual(set(re.findall(r"__[A-Z][A-Z_]*__", text)), set(TOKENS))
        self.assertIn("color-mix(in srgb, currentColor", text)
        self.assertIn("navigator.clipboard", text)
        self.assertIn("execCommand", text)
        text.encode("ascii")

    def test_a_template_that_lost_a_token_is_refused(self):
        import shutil
        copy = os.path.join(self.tmp, "copy")
        os.makedirs(copy)
        shutil.copy(os.path.join(os.path.dirname(os.path.dirname(__file__)), "source_chat_footer.py"), copy)
        write(os.path.join(copy, "footer-snippet.html"), START + "\n<p>__SESSION_ID__</p>\n" + END + "\n")
        path = self.page("p.html")
        proc = self.run_tool("add", path, "--session", S1, "--transcript", self.trace,
                             tool=os.path.join(copy, "source_chat_footer.py"))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(read(path).decode(), PLAIN)


if __name__ == "__main__":
    unittest.main()
