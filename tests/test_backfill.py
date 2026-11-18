import json
import os
import re
import stat
import unittest

from _common import Base, PLAIN, ROOT, S1, S2, S3, epoch, read, write

START = "<!-- source-chat-footer:start -->"
OLD = epoch(2025, 6, 1)


def write_line(path, ts=None, name="Write"):
    tool_input = {"file_path": path}
    tool_input.update({"content": "x"} if name == "Write" else {"old_string": "a", "new_string": "b"})
    obj = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": name, "input": tool_input}]}}
    if ts:
        obj["timestamp"] = ts
    return obj


def mention_line(path, ts=None, tool="Read"):
    obj = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t2", "name": tool, "input": {"file_path": path}}]}}
    if ts:
        obj["timestamp"] = ts
    return obj


def summary(out):
    """The summary block as {label: number}, with the dry-run verb folded away."""
    found = {}
    lines = out.splitlines()
    for line in lines[lines.index("summary") + 1:]:
        m = re.match(r"^(?:would link|linked) (by a (?:write|mention)): (\d+)$", line)
        if m:
            found[m.group(1)] = int(m.group(2))
            continue
        m = re.match(r"^([A-Za-z0-9 -]+): (\d+)$", line)
        if m:
            found[m.group(1)] = int(m.group(2))
    return found


class BackfillCase(Base):
    def backfill(self, *args, root=None):
        return self.run_tool("backfill", root or self.docs, *args)

    def pg(self, rel="p.html", text=PLAIN):
        return self.page(rel, text, mtime=OLD)

    def main(self, session=S1, project="proj-a", lines=None, mtime=None):
        return self.transcript(session, lines or [{"type": "user", "message": "hello"}],
                               project=project, mtime=mtime)

    def footer_of(self, path):
        text = read(path).decode()
        self.assertEqual(text.count(START), 1, text)
        return text


class WriteTier(BackfillCase):
    def test_write_call_links_the_session(self):
        page = self.pg()
        trace = self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply")
        self.assertEqual((proc.returncode, proc.err), (0, ""), proc.err)
        text = self.footer_of(page)
        self.assertIn('data-source-chat="%s" data-link-confidence="wrote"' % S1, text)
        self.assertIn('<span class="source-chat__label">Source chat</span>', text)
        self.assertIn(">%s</a>" % trace, text)
        self.assertIn("linked %s %s wrote\n" % (page, S1), proc.out)

    def test_edit_call_counts_as_a_write(self):
        page = self.pg()
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z", name="Edit")])
        proc = self.backfill("--apply")
        self.assertIn("linked %s %s wrote\n" % (page, S1), proc.out)
        self.assertIn('data-link-confidence="wrote"', self.footer_of(page))

    def test_other_tools_and_relative_paths_are_not_writes(self):
        page = self.pg()
        self.main(lines=[mention_line(page, tool="Read"), write_line("p.html"),
                         write_line(page, name="MultiEdit")])
        proc = self.backfill("--apply")
        self.assertEqual(summary(proc.out)["by a write"], 0)
        self.assertEqual(read(page).decode(), PLAIN)

    def latest(self, first_project_holds):
        """Two sessions wrote the page; the one with the later line time wins."""
        page = self.pg()
        late, early = first_project_holds
        self.main(session=late, project="p1", lines=[write_line(page, "2026-01-02T10:00:00Z")])
        self.main(session=early, project="p2", lines=[write_line(page, "2026-01-01T10:00:00Z")])
        self.backfill("--apply")
        text = self.footer_of(page)
        self.assertIn('data-source-chat="%s"' % late, text)

    def test_latest_write_wins_when_it_is_in_the_first_file(self):
        self.latest((S1, S2))

    def test_latest_write_wins_when_it_is_in_the_last_file(self):
        page = self.pg()
        self.main(session=S1, project="p1", lines=[write_line(page, "2026-01-01T10:00:00Z")])
        self.main(session=S2, project="p2", lines=[write_line(page, "2026-01-02T10:00:00Z")])
        self.backfill("--apply")
        self.assertIn('data-source-chat="%s"' % S2, self.footer_of(page))

    def test_time_zone_offsets_are_honoured(self):
        page = self.pg()
        self.main(session=S1, project="p1", lines=[write_line(page, "2026-01-02T00:30:00+05:00")])
        self.main(session=S2, project="p2", lines=[write_line(page, "2026-01-01T20:00:00.250Z")])
        self.backfill("--apply")
        self.assertIn('data-source-chat="%s"' % S2, self.footer_of(page))

    def test_a_line_without_a_usable_time_uses_the_file_time(self):
        page = self.pg()
        self.main(session=S1, project="p1", lines=[write_line(page)], mtime=epoch(2026, 5, 1))
        self.main(session=S2, project="p2", lines=[write_line(page, "2026-01-01T10:00:00Z")])
        self.backfill("--apply")
        self.assertIn('data-source-chat="%s"' % S1, self.footer_of(page))

    def test_an_unusable_time_string_uses_the_file_time(self):
        page = self.pg()
        self.main(session=S1, project="p1", lines=[write_line(page, "not a time")], mtime=epoch(2024, 5, 1))
        self.main(session=S2, project="p2", lines=[write_line(page, "2026-01-01T10:00:00Z")])
        self.backfill("--apply")
        self.assertIn('data-source-chat="%s"' % S2, self.footer_of(page))

    def test_a_write_beats_a_mention(self):
        for write_time, mention_time in (("2026-01-09T00:00:00Z", "2026-01-01T00:00:00Z"),
                                         ("2026-01-01T00:00:00Z", "2026-01-09T00:00:00Z")):
            page = self.pg("p-%s.html" % write_time[:10])
            self.main(session=S1, project="p1-" + write_time[:10], lines=[mention_line(page, mention_time)])
            self.main(session=S2, project="p2-" + write_time[:10], lines=[write_line(page, write_time)])
        self.backfill("--apply")
        for name in os.listdir(self.docs):
            text = self.footer_of(os.path.join(self.docs, name))
            self.assertIn('data-source-chat="%s" data-link-confidence="wrote"' % S2, text)

    def test_date_comes_from_the_pages_modification_time(self):
        page = self.page("p.html", mtime=epoch(2026, 3, 4))
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        self.backfill("--apply")
        self.assertIn("<span>generated 2026-03-04</span>", self.footer_of(page))

    def test_page_named_through_a_symlinked_folder_still_matches(self):
        page = self.pg(os.path.join("real", "p.html"))
        alias = os.path.join(self.tmp, "alias")
        os.symlink(os.path.join(self.docs, "real"), alias)
        self.main(lines=[write_line(os.path.join(alias, "p.html"), "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply")
        self.assertIn("linked %s %s wrote\n" % (page, S1), proc.out)

    def test_page_reached_through_a_symlinked_root_matches_by_real_path(self):
        page = self.pg(os.path.join("real", "p.html"))
        link_root = os.path.join(self.tmp, "link_root")
        os.symlink(os.path.join(self.docs, "real"), link_root)
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.run_tool("backfill", link_root, "--apply")
        self.assertEqual(summary(proc.out)["by a write"], 1, proc.out)
        self.assertEqual(self.blocks(read(page)), 1)


class MentionTier(BackfillCase):
    def test_a_mention_is_reported_and_not_written_without_infer(self):
        page = self.pg()
        self.main(lines=[mention_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(read(page).decode(), PLAIN)
        self.assertIn("guess %s %s mentioned" % (page, S1), proc.out)
        self.assertIn("--infer", [l for l in proc.out.splitlines() if l.startswith("guess")][0])
        counts = summary(proc.out)
        self.assertEqual((counts["guesses not linked"], counts["by a mention"]), (1, 0))

    def test_infer_writes_the_inferred_footer(self):
        page = self.pg()
        trace = self.main(lines=[mention_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply", "--infer")
        self.assertIn("linked %s %s mentioned\n" % (page, S1), proc.out)
        text = self.footer_of(page)
        self.assertIn('data-source-chat="%s" data-link-confidence="mentioned"' % S1, text)
        self.assertIn('<span class="source-chat__label">Source chat (inferred)</span>', text)
        self.assertIn(">%s</a>" % trace, text)

    def test_infer_in_a_dry_run_changes_nothing_and_says_would_link(self):
        page = self.pg()
        self.main(lines=[mention_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--infer")
        self.assertIn("would link %s %s mentioned\n" % (page, S1), proc.out)
        self.assertEqual(read(page).decode(), PLAIN)

    def test_earliest_mention_wins_in_either_file_order(self):
        for early_in_first in (True, False):
            page = self.pg("p-%s.html" % early_in_first)
            first, second = (S1, S2) if early_in_first else (S2, S1)
            tag = str(early_in_first)
            self.main(session=first, project="p1" + tag, lines=[mention_line(page, "2026-01-01T00:00:00Z")])
            self.main(session=second, project="p2" + tag, lines=[mention_line(page, "2026-01-05T00:00:00Z")])
            self.backfill("--apply", "--infer")
            self.assertIn('data-source-chat="%s"' % first, self.footer_of(page))

    def test_mention_by_the_real_path_when_the_root_is_a_link(self):
        page = self.pg(os.path.join("real", "p.html"))
        link_root = os.path.join(self.tmp, "link_root")
        os.symlink(os.path.join(self.docs, "real"), link_root)
        self.main(lines=[mention_line(page, "2026-01-02T10:00:00Z")])
        proc = self.run_tool("backfill", link_root, "--infer", "--apply")
        self.assertEqual(summary(proc.out)["by a mention"], 1, proc.out)

    def test_mention_by_the_path_as_walked_when_the_root_is_a_link(self):
        self.pg(os.path.join("real", "p.html"))
        link_root = os.path.join(self.tmp, "link_root")
        os.symlink(os.path.join(self.docs, "real"), link_root)
        self.main(lines=[mention_line(os.path.join(link_root, "p.html"), "2026-01-02T10:00:00Z")])
        proc = self.run_tool("backfill", link_root)
        self.assertEqual(summary(proc.out)["guesses not linked"], 1, proc.out)


class TranscriptLayout(BackfillCase):
    def test_helper_transcript_links_the_parent_session_and_its_main_transcript(self):
        page = self.pg()
        trace = self.main()
        helper = os.path.join(self.projects, "proj-a", S1, "subagents", "agent-a1.jsonl")
        self.transcript_at(helper, [write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply")
        self.assertIn("linked %s %s wrote\n" % (page, S1), proc.out)
        text = self.footer_of(page)
        self.assertIn('data-source-chat="%s"' % S1, text)
        self.assertNotIn("agent-a1", text)
        self.assertIn(">%s</a>" % trace, text)

    def test_helper_mention_links_the_parent_session(self):
        page = self.pg()
        self.main()
        helper = os.path.join(self.projects, "proj-a", S1, "deep", "er", "agent-a1.jsonl")
        self.transcript_at(helper, [mention_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply", "--infer")
        self.assertIn("linked %s %s mentioned\n" % (page, S1), proc.out)

    def test_helper_without_a_main_transcript_is_ignored(self):
        page = self.pg()
        self.main(session=S3)
        helper = os.path.join(self.projects, "proj-a", S1, "subagents", "agent-a1.jsonl")
        self.transcript_at(helper, [write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply", "--infer")
        self.assertIn("no session %s\n" % page, proc.out)
        self.assertEqual(read(page).decode(), PLAIN)

    def test_helper_whose_main_is_in_another_project_is_ignored(self):
        page = self.pg()
        self.main(project="proj-b")
        helper = os.path.join(self.projects, "proj-a", S1, "subagents", "agent-a1.jsonl")
        self.transcript_at(helper, [write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply", "--infer")
        self.assertIn("no session %s\n" % page, proc.out)

    def test_agent_file_directly_in_a_project_folder_is_ignored(self):
        page = self.pg()
        self.transcript_at(os.path.join(self.projects, "proj-a", "agent-zzz.jsonl"),
                           [write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply", "--infer")
        self.assertIn("no session %s\n" % page, proc.out)

    def test_other_jsonl_files_are_ignored(self):
        page = self.pg()
        line = [write_line(page, "2026-01-02T10:00:00Z")]
        self.transcript_at(os.path.join(self.projects, "stray.jsonl"), line)
        self.transcript_at(os.path.join(self.projects, "proj-a", "bad name.jsonl"), line)
        self.transcript_at(os.path.join(self.projects, "proj-a", "notes", "x.jsonl"), line)
        self.transcript_at(os.path.join(self.projects, "proj-a", S1 + ".jsonl.bak"), line)
        proc = self.backfill("--apply", "--infer")
        self.assertIn("no session %s\n" % page, proc.out)

    def test_broken_lines_are_skipped(self):
        page = self.pg()
        self.main(lines=[
            "not json at all .html",
            b"\xff\xfe\x00 broken .htm bytes",
            "[1, 2, \"%s\"]" % page,
            '{"message": {"content": "%s"}}' % page,
            '{"message": {"content": [1, "x.html", {"type": "tool_use"}, {"type": "tool_use", "name": "Write", "input": 5}]}}',
            '{"timestamp": "2026-01-01T00:00:00Z", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "%s' % page,
            write_line(page, "2026-01-02T10:00:00Z"),
        ])
        proc = self.backfill("--apply")
        self.assertEqual((proc.returncode, proc.err), (0, ""))
        self.assertIn('data-source-chat="%s"' % S1, self.footer_of(page))

    def test_a_json_value_that_is_not_an_object_still_counts_as_a_mention(self):
        page = self.pg()
        self.main(lines=["[\"%s\"]" % page])
        proc = self.backfill()
        self.assertEqual(summary(proc.out)["guesses not linked"], 1)


class Pages(BackfillCase):
    def mixed_tree(self):
        self.main(session=S1, project="p1", lines=[write_line(self.docs + "/written.html", "2026-01-02T10:00:00Z"),
                                                   write_line(self.docs + "/UPPER.HTM", "2026-01-02T10:00:00Z"),
                                                   mention_line(self.docs + "/mentioned.html", "2026-01-03T00:00:00Z")])
        self.main(session=S2, project="p2", lines=[write_line(self.docs + "/edited.html", "2026-01-04T00:00:00Z", name="Edit"),
                                                   write_line(self.docs + "/node_modules/skip.html", "2026-01-04T00:00:00Z"),
                                                   write_line(self.docs + "/skipme/x.html", "2026-01-04T00:00:00Z")])
        for name in ("written.html", "UPPER.HTM", "mentioned.html", "edited.html", "none.html"):
            self.pg(name)
        self.pg(os.path.join("node_modules", "skip.html"))
        self.pg(os.path.join("skipme", "x.html"))
        self.pg("template.html", "<p>__SESSION_ID__</p>")
        self.pg("optc.html", "<p>x</p><!-- no-source-chat -->")
        write(os.path.join(self.docs, "quiet", ".no-source-chat"), "")
        self.pg(os.path.join("quiet", "optf.html"))
        self.pg("latin1.html", b"<p>caf\xe9</p>")
        linked = self.pg("linked.html")
        proc = self.run_tool("add", linked, "--session", S3, "--transcript", self.main(session=S3, project="p3"))
        self.assertEqual(proc.returncode, 0, proc.err)
        os.symlink(linked, os.path.join(self.docs, "sym.html"))
        os.utime(linked, (OLD, OLD))

    def test_exact_summary_for_a_mixed_tree(self):
        self.mixed_tree()
        before = self.tree_state(self.docs)
        proc = self.backfill("--skip-dir", "skipme")
        self.assertEqual((proc.returncode, proc.err), (0, ""))
        self.assertEqual(self.tree_state(self.docs), before)
        self.assertEqual(summary(proc.out), {
            "pages found": 10, "already linked": 1, "templates": 1, "opted out": 2,
            "not UTF-8": 1, "symlinks left alone": 1, "by a write": 3, "by a mention": 0,
            "guesses not linked": 1, "no session found": 1, "could not write": 0})
        lines = proc.out.splitlines()
        self.assertEqual(lines[-1], "dry run: nothing was changed; add --apply to write the footers")
        self.assertIn("would link %s/written.html %s wrote" % (self.docs, S1), lines)
        self.assertIn("would link %s/edited.html %s wrote" % (self.docs, S2), lines)
        self.assertIn("would link %s/UPPER.HTM %s wrote" % (self.docs, S1), lines)
        self.assertIn("no session %s/none.html" % self.docs, lines)
        self.assertIn("not utf-8 %s/latin1.html" % self.docs, lines)
        self.assertTrue(any(l.startswith("guess %s/mentioned.html" % self.docs) for l in lines))
        detail = ("would link /", "guess /", "no session /", "not utf-8 /")
        self.assertEqual(len([l for l in lines if l.startswith(detail)]), 6)
        self.assertNotIn("node_modules", proc.out)
        self.assertNotIn("skipme", proc.out)
        self.assertNotIn("sym.html", proc.out)

    def test_apply_with_infer_on_the_mixed_tree(self):
        self.mixed_tree()
        proc = self.backfill("--skip-dir", "skipme", "--apply", "--infer")
        self.assertEqual(proc.returncode, 0)
        counts = summary(proc.out)
        self.assertEqual((counts["by a write"], counts["by a mention"], counts["guesses not linked"]), (3, 1, 0))
        self.assertEqual(proc.out.splitlines()[-1], "applied: the footers above were written")
        for name in ("written.html", "UPPER.HTM", "mentioned.html", "edited.html"):
            self.footer_of(os.path.join(self.docs, name))
        for name in ("none.html", "template.html", "optc.html", os.path.join("quiet", "optf.html")):
            self.assertNotIn(START, read(os.path.join(self.docs, name)).decode())
        self.assertEqual(read(os.path.join(self.docs, "latin1.html")), b"<p>caf\xe9</p>")
        self.assertTrue(os.path.islink(os.path.join(self.docs, "sym.html")))
        self.assertEqual(self.blocks(read(os.path.join(self.docs, "skipme", "x.html"))), 0)
        self.assertEqual(self.blocks(read(os.path.join(self.docs, "node_modules", "skip.html"))), 0)

    def test_second_apply_links_nothing_new(self):
        self.mixed_tree()
        self.backfill("--skip-dir", "skipme", "--apply", "--infer")
        first = self.tree_state(self.docs)
        proc = self.backfill("--skip-dir", "skipme", "--apply", "--infer")
        counts = summary(proc.out)
        self.assertEqual((counts["by a write"], counts["by a mention"]), (0, 0))
        self.assertEqual(counts["already linked"], 5)
        self.assertEqual(self.tree_state(self.docs), first)

    def test_dry_run_changes_no_byte_and_no_modification_time(self):
        self.mixed_tree()
        docs, projects = self.tree_state(self.docs), self.tree_state(self.projects)
        proc = self.backfill("--infer")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.tree_state(self.docs), docs)
        self.assertEqual(self.tree_state(self.projects), projects)
        self.assertIn("would link", proc.out)
        self.assertEqual(os.listdir(self.state) if os.path.exists(self.state) else [], [])

    def test_skipped_folder_names_are_pruned(self):
        page = self.pg(os.path.join("vendor", "x", "p.html"))
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply")
        self.assertEqual(summary(proc.out)["pages found"], 0)
        self.assertEqual(read(page).decode(), PLAIN)

    def test_a_root_below_a_skipped_name_finds_nothing(self):
        page = self.pg(os.path.join("src", "inner", "p.html"))
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.backfill("--apply", root=os.path.join(self.docs, "src", "inner"))
        self.assertEqual(summary(proc.out)["pages found"], 0)

    def test_skip_dir_option_is_repeatable(self):
        for name in ("one", "two", "three"):
            self.pg(os.path.join(name, "p.html"))
        proc = self.backfill("--skip-dir", "one", "--skip-dir", "two")
        self.assertEqual(summary(proc.out)["pages found"], 1)

    def test_symlinked_folders_are_not_followed_and_symlinked_pages_are_counted(self):
        self.pg(os.path.join("real", "p.html"))
        os.symlink(os.path.join(self.docs, "real"), os.path.join(self.docs, "alias"))
        os.symlink(os.path.join(self.docs, "real", "p.html"), os.path.join(self.docs, "link.html"))
        os.symlink(os.path.join(self.docs, "gone.html"), os.path.join(self.docs, "broken.html"))
        proc = self.backfill()
        counts = summary(proc.out)
        self.assertEqual((counts["pages found"], counts["symlinks left alone"]), (1, 2))

    def test_the_same_page_through_two_roots_is_counted_once(self):
        self.pg()
        proc = self.run_tool("backfill", self.docs, self.docs + "/")
        self.assertEqual(summary(proc.out)["pages found"], 1)

    def test_every_line_is_printed_with_no_cut(self):
        for i in range(40):
            self.pg("page-%02d.html" % i)
        self.main()
        proc = self.backfill()
        self.assertEqual(len([l for l in proc.out.splitlines() if l.startswith("no session /")]), 40)
        self.assertNotIn("...", proc.out)

    def test_summary_prints_every_count_including_zeros(self):
        self.main()
        proc = self.backfill()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(summary(proc.out), {
            "pages found": 0, "already linked": 0, "templates": 0, "opted out": 0,
            "not UTF-8": 0, "symlinks left alone": 0, "by a write": 0, "by a mention": 0,
            "guesses not linked": 0, "no session found": 0, "could not write": 0})


class ExitCodes(BackfillCase):
    def test_zero_when_there_is_nothing_to_link(self):
        self.main()
        self.assertEqual(self.backfill("--apply").returncode, 0)

    def test_two_when_a_root_is_not_a_folder(self):
        page = self.pg()
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        proc = self.run_tool("backfill", self.docs, os.path.join(self.tmp, "missing"), "--apply")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(read(page).decode(), PLAIN)
        self.assertEqual(len(proc.err.strip().splitlines()), 1)
        proc = self.run_tool("backfill", page)
        self.assertEqual(proc.returncode, 2)

    def test_two_when_the_projects_folder_is_missing(self):
        page = self.pg()
        os.rmdir(self.projects)
        proc = self.backfill("--apply")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.out, "")
        self.assertIn("projects folder", proc.err)
        self.assertNotIn("Traceback", proc.err)
        self.assertEqual(read(page).decode(), PLAIN)

    def test_one_when_a_page_cannot_be_written_and_the_others_are_linked(self):
        self.skip_if_root()
        good = self.pg("good.html")
        locked = self.pg(os.path.join("ro", "locked.html"))
        self.main(lines=[write_line(good, "2026-01-02T10:00:00Z"), write_line(locked, "2026-01-02T10:00:00Z")])
        os.chmod(os.path.dirname(locked), 0o555)
        self.addCleanup(os.chmod, os.path.dirname(locked), 0o755)
        proc = self.backfill("--apply")
        self.assertEqual(proc.returncode, 1, proc.out + proc.err)
        self.assertIn("could not write %s" % locked, proc.out)
        counts = summary(proc.out)
        self.assertEqual((counts["could not write"], counts["by a write"]), (1, 1))
        self.assertEqual(self.blocks(read(good)), 1)
        self.assertEqual(read(locked).decode(), PLAIN)
        self.assertNotIn("Traceback", proc.err)

    def test_one_when_a_page_cannot_be_read(self):
        self.skip_if_root()
        page = self.pg()
        os.chmod(page, 0)
        self.addCleanup(os.chmod, page, 0o644)
        self.main()
        proc = self.backfill()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("could not read %s" % page, proc.out)
        self.assertEqual(summary(proc.out)["could not write"], 1)

    def test_one_when_a_page_changes_while_the_transcripts_are_scanned(self):
        """source: a backfill run wrote the text it read before the scan over an edit made during the scan."""
        page = self.pg()
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        edited = PLAIN + "<p>added during the scan</p>\n"
        driver = os.path.join(self.tmp, "edit_during_scan.py")
        write(driver, "\n".join([
            "import sys",
            "sys.path.insert(0, %r)" % ROOT,
            "import source_chat_footer as tool",
            "scan = tool.scan_transcripts",
            "def edit_then_scan(*args):",
            "    with open(%r, 'w', encoding='utf-8') as fh:" % page,
            "        fh.write(%r)" % edited,
            "    return scan(*args)",
            "tool.scan_transcripts = edit_then_scan",
            "sys.exit(tool.main())",
            "",
        ]))
        proc = self.run_tool("backfill", self.docs, "--apply", tool=driver)
        self.assertEqual(proc.returncode, 1, proc.out + proc.err)
        self.assertEqual(read(page).decode(), edited)
        self.assertIn("changed while backfill ran", proc.out)
        self.assertEqual(summary(proc.out)["could not write"], 1)
        self.assertNotIn("Traceback", proc.err)

    def test_page_permissions_survive_a_backfill(self):
        page = self.pg()
        os.chmod(page, 0o640)
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        self.backfill("--apply")
        self.assertEqual(stat.S_IMODE(os.stat(page).st_mode), 0o640)

    def test_no_roots_is_a_usage_error(self):
        proc = self.run_tool("backfill")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.err)


class Roundtrip(BackfillCase):
    def test_a_backfilled_page_is_then_silent_for_the_hook(self):
        page = self.pg()
        self.main(lines=[write_line(page, "2026-01-02T10:00:00Z")])
        self.backfill("--apply")
        proc = self.hook(self.hook_input(S1, page))
        self.assertEqual((proc.returncode, proc.out), (0, ""))
        self.assertEqual(json.loads(json.dumps(1)), 1)


if __name__ == "__main__":
    unittest.main()
