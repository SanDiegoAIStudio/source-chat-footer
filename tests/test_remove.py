import os
import stat
import unittest

from _common import Base, PLAIN, S1, read, write

START = "<!-- source-chat-footer:start -->"
END = "<!-- source-chat-footer:end -->"
COMMENT = "<!-- no-source-chat -->"


class RemoveCase(Base):
    def setUp(self):
        super().setUp()
        self.trace = self.transcript(S1)

    def stamped(self, text=PLAIN, name="p.html"):
        path = self.page(name, text)
        proc = self.run_tool("add", path, "--session", S1, "--transcript", self.trace)
        self.assertEqual(proc.returncode, 0, proc.err)
        return path

    def remove(self, path):
        return self.run_tool("remove", path)


class Removal(RemoveCase):
    def test_block_is_gone_and_the_comment_is_left(self):
        path = self.stamped()
        proc = self.remove(path)
        self.assertEqual((proc.returncode, proc.out, proc.err), (0, "removed %s\n" % path, ""))
        self.assertEqual(read(path).decode(), "<html><body><p>hi</p>\n" + COMMENT + "\n</body></html>\n")

    def test_afterwards_the_hook_is_silent_and_add_refuses(self):
        path = self.stamped()
        self.remove(path)
        hook = self.hook(self.hook_input("dddddddd-0000-4000-8000-00000000000d", path, transcript=self.trace))
        self.assertEqual((hook.returncode, hook.out), (0, ""))
        hook = self.hook(self.hook_input(S1, path))
        self.assertEqual((hook.returncode, hook.out), (0, ""))
        before = read(path)
        proc = self.run_tool("add", path, "--session", S1, "--transcript", self.trace)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(COMMENT, proc.err)
        self.assertEqual(read(path), before)

    def test_afterwards_backfill_leaves_the_page_alone(self):
        path = self.stamped(name="b.html")
        self.remove(path)
        before = read(path)
        proc = self.run_tool("backfill", self.docs, "--apply", "--infer")
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertIn("opted out: 1", proc.out)
        self.assertEqual(read(path), before)

    def test_page_with_the_comment_already_does_not_get_a_second_one(self):
        path = self.stamped()
        text = read(path).decode().replace("</body>", COMMENT + "\n</body>")
        write(path, text)
        self.remove(path)
        out = read(path).decode()
        self.assertEqual(out.count(COMMENT), 1)
        self.assertNotIn(START, out)

    def test_two_blocks_leave_one_comment_where_the_first_was(self):
        path = self.stamped()
        text = read(path).decode()
        block = text[text.index(START):text.index(END) + len(END)]
        write(path, "<body>\n" + block + "\n<p>middle</p>\n" + block + "\n</body>\n")
        proc = self.remove(path)
        self.assertEqual(proc.returncode, 0)
        out = read(path).decode()
        self.assertEqual(out, "<body>\n" + COMMENT + "\n<p>middle</p>\n</body>\n")

    def test_no_footer_changes_nothing(self):
        path = self.page("p.html")
        os.utime(path, (1000000000, 1000000000))
        proc = self.remove(path)
        self.assertEqual((proc.returncode, proc.out, proc.err), (0, "no footer found %s\n" % path, ""))
        self.assertEqual(read(path).decode(), PLAIN)
        self.assertEqual(os.stat(path).st_mtime, 1000000000)

    def test_symlinked_page_changes_the_real_file(self):
        real = self.stamped(name="real.html")
        link = os.path.join(self.docs, "link.html")
        os.symlink(real, link)
        proc = self.remove(link)
        self.assertEqual(proc.out, "removed %s\n" % real)
        self.assertTrue(os.path.islink(link))
        self.assertNotIn(START, read(real).decode())

    def test_permission_bits_and_bom_and_crlf_are_kept(self):
        path = self.stamped("\ufeff<html>\r\n<body>\r\n</body>\r\n</html>\r\n")
        os.chmod(path, 0o640)
        self.remove(path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
        data = read(path)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf<html>\r\n<body>\r\n"))
        self.assertTrue(data.endswith(b"</body>\r\n</html>\r\n"))

    def test_remove_works_inside_a_skipped_folder(self):
        path = self.stamped(name=os.path.join("node_modules", "p.html"))
        self.assertEqual(self.remove(path).returncode, 0)
        self.assertNotIn(START, read(path).decode())


class Refusals(RemoveCase):
    def refused(self, path, before=None):
        proc = self.remove(path)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.out, "")
        self.assertEqual(len(proc.err.strip().splitlines()), 1)
        self.assertNotIn("Traceback", proc.err)
        if before is not None:
            self.assertEqual(read(path), before)

    def test_not_an_existing_page(self):
        self.refused(os.path.join(self.docs, "missing.html"))
        self.refused(self.page("notes.txt", START + "x" + END))

    def test_not_utf8(self):
        path = self.page("p.html", b"\xff\xfe" + START.encode() + END.encode())
        self.refused(path, read(path))

    def test_start_mark_without_end_mark(self):
        path = self.page("p.html", "<p>x</p>" + START + "tail")
        self.refused(path, read(path))
        path = self.page("q.html", START + "a" + END + "\n" + START + "b")
        self.refused(path, read(path))


if __name__ == "__main__":
    unittest.main()
