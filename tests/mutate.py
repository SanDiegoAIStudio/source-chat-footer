"""Mutation run: break the tool on purpose and check that the test suite notices.

Each mutation is a small text change to source_chat_footer.py. It is applied to a
fresh temporary copy of this folder (no __pycache__), the whole suite runs in that
copy, and the mutation counts as killed when the suite fails. A mutation that
survives means a test is missing.

Run: python3 tests/mutate.py          (exit 1 when any mutation survived)
"""
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = "source_chat_footer.py"
WORKERS = 4
TIMEOUT = 900

# (name, text in the tool that must occur exactly once, replacement)
MUTATIONS = [
    ("hook reminds for a non-HTML file",
     "    if is_page_name(real) and os.path.isfile(real):",
     "    if os.path.isfile(real):"),
    ("hook ignores SKIP_DIRS",
     "    if is_skipped(real, args.skip_dir):\n        return\n",
     "    if False:\n        return\n"),
    ("hook ignores --skip-dir",
     "    if is_skipped(real, args.skip_dir):\n        return\n",
     "    if is_skipped(real):\n        return\n"),
    ("hook ignores the opt-out file",
     "    if find_opt_out_file(real) is not None:\n        return \"opted_out\", None",
     "    if False:\n        return \"opted_out\", None"),
    ("hook ignores the opt-out comment",
     "    if OPT_OUT_COMMENT in text:\n        return \"opted_out\", text",
     "    if False:\n        return \"opted_out\", text"),
    ("hook reminds when the page holds the session id",
     "    if session in text:\n        return\n",
     "    if False:\n        return\n"),
    ("hook reminds for a template",
     "    if status in (\"opted_out\", \"not_utf8\", \"template\"):",
     "    if status in (\"opted_out\", \"not_utf8\"):"),
    ("hook ignores the marker",
     "    if os.path.exists(marker):\n        return\n",
     "    if False:\n        return\n"),
    ("marker name leaves out the session",
     "(\"%s|%s\" % (session, real))",
     "(\"%s\" % (real,))"),
    ("marker name leaves out the path",
     "(\"%s|%s\" % (session, real))",
     "(\"%s\" % (session,))"),
    ("marker is written when no transcript is found",
     "    if trace is None:\n        print(json.dumps({\"systemMessage\": (",
     "    if trace is None:\n        os.makedirs(state_dir(), exist_ok=True)\n"
     "        open(marker, \"ab\").close()\n        print(json.dumps({\"systemMessage\": ("),
    ("hook exits 1 on bad JSON",
     "    except (ValueError, RecursionError):\n        return\n    if not isinstance(obj, dict):",
     "    except (ValueError, RecursionError):\n        sys.exit(1)\n    if not isinstance(obj, dict):"),
    ("--quiet still prints the routine message",
     "    if not args.quiet:\n        out[\"systemMessage\"]",
     "    if True:\n        out[\"systemMessage\"]"),
    ("hook ignores tool_input.file_path",
     "        value = tool_input.get(\"file_path\")",
     "        value = None"),
    ("the add command is printed without quoting",
     "shlex.quote(part) for part in [",
     "str(part) for part in ["),
    ("transcript lookup takes the oldest file",
     "key=lambda p: (-os.path.getmtime(p), p))[0]",
     "key=lambda p: (os.path.getmtime(p), p))[0]"),
    ("transcript hint is ignored",
     "        if os.path.isfile(hint) and os.path.basename(hint) == name:",
     "        if False:"),
    ("add keeps the old block",
     "    text, count = strip_blocks(text)\n    matches",
     "    count = 0\n    matches"),
    ("add inserts before the first </body>",
     "        at = matches[-1].start()",
     "        at = matches[0].start()"),
    ("add does not escape the path",
     "    return TOKEN_RE.sub(",
     "    escaped[\"__TRACE_PATH__\"] = trace\n    return TOKEN_RE.sub("),
    ("add builds the link without percent-encoding",
     "\"__TRACE_URL__\": pathlib.Path(trace).as_uri(),",
     "\"__TRACE_URL__\": \"file://\" + trace,"),
    ("add writes when no transcript is found",
     "    if trace is None:\n        raise Refusal(\"no transcript found for session %s\" % args.session)\n",
     "    if trace is None:\n        trace = args.transcript or \"/nowhere/x.jsonl\"\n"),
    ("add ignores the opt-out",
     "    refuse_status(real, status)\n",
     "    if status != \"opted_out\":\n        refuse_status(real, status)\n"),
    ("add rewrites a page that is not UTF-8",
     "        return \"not_utf8\", None",
     "        return \"plain\", raw.decode(\"utf-8\", \"replace\")"),
    ("add accepts a date that is not real",
     "            datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))",
     "            pass"),
    ("add is not idempotent",
     "        return text[:at] + block + \"\\n\" + text[at:], count > 0",
     "        return text[:at] + block + \"\\n\\n\" + text[at:], count > 0"),
    ("add drops the permission bits",
     "        os.chmod(tmp, mode)\n",
     "        pass\n"),
    ("a symlinked page is rewritten in place of its link",
     "    real = os.path.realpath(path)\n    if is_page_name(real)",
     "    real = os.path.abspath(path)\n    if is_page_name(real)"),
    ("remove leaves no comment",
     "    replacement = \"\" if OPT_OUT_COMMENT in text else OPT_OUT_COMMENT + \"\\n\"",
     "    replacement = \"\""),
    ("backfill writes in a dry run",
     "        if args.apply:\n            label =",
     "        if True:\n            label ="),
    ("backfill links a guess without --infer",
     "            if not args.infer:\n                counts[\"guesses\"] += 1",
     "            if False:\n                counts[\"guesses\"] += 1"),
    ("backfill write tier takes the earliest",
     "if best is None or stamp > best[0] or (stamp == best[0] and main < best[1]):",
     "if best is None or stamp < best[0] or (stamp == best[0] and main < best[1]):"),
    ("backfill mention tier takes the latest",
     "if best is None or stamp < best[0] or (stamp == best[0] and main < best[1]):",
     "if best is None or stamp > best[0] or (stamp == best[0] and main < best[1]):"),
    ("backfill links a helper transcript as its own session",
     "found.append((mains[name], name, os.path.join(base, fname)))",
     "found.append((os.path.join(base, fname), fname[:-len(\".jsonl\")], os.path.join(base, fname)))"),
    ("backfill does not count a symlinked page",
     "                if os.path.islink(full):\n                    links += 1\n                    continue\n",
     "                if False:\n                    links += 1\n                    continue\n"),
    ("backfill ignores skipped names above a root",
     "                if is_skipped(os.path.join(os.path.realpath(base), fname), extra_skip):\n                    continue\n",
     "                if False:\n                    continue\n"),
    ("backfill dates the footer today",
     "local_date(mtime))",
     "datetime.date.today().isoformat())"),
    ("backfill exits 0 when a page could not be written",
     "    return 1 if counts[\"could_not\"] else 0",
     "    return 0"),
    ("backfill exits 0 when the projects folder is missing",
     "        raise Refusal(\"the projects folder %s does not exist\" % projects)",
     "        return 0"),
    ("Edit calls are not counted as writes",
     "if block.get(\"name\") not in (\"Write\", \"Edit\"):",
     "if block.get(\"name\") not in (\"Write\",):"),
    ("backfill writes over a page edited during its scan",
     "                if page_status(real) != (\"plain\", text):",
     "                if False:"),
]

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")


def run_suite(name, old, new):
    """Return (name, state) with state 'killed', 'survived' or 'error: ...'."""
    work = tempfile.mkdtemp(prefix="scf-mutate-")
    try:
        copy = os.path.join(work, "copy")
        shutil.copytree(ROOT, copy, ignore=IGNORE)
        if old is not None:
            path = os.path.join(copy, TOOL)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            if text.count(old) != 1:
                return name, "error: the text to change occurs %d times, not once" % text.count(old)
            changed = text.replace(old, new)
            if changed == text:
                return name, "error: the copy did not differ"
            try:
                compile(changed, TOOL, "exec")
            except SyntaxError as exc:
                return name, "error: the mutated file does not compile (%s)" % exc
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(changed)
        env = dict(os.environ)
        for key in ("CLAUDE_CONFIG_DIR", "SOURCE_CHAT_STATE_DIR", "XDG_CACHE_HOME"):
            env.pop(key, None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-f"],
                cwd=copy, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return name, "killed"
        if old is None:
            return name, "baseline-ok" if proc.returncode == 0 else "baseline-failed"
        return name, "killed" if proc.returncode != 0 else "survived"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    names = [m[0] for m in MUTATIONS]
    if len(set(names)) != len(names):
        print("error: duplicate mutation names")
        return 2
    jobs = [("unmutated copy", None, None)] + MUTATIONS
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for name, state in pool.map(lambda job: run_suite(*job), jobs):
            results[name] = state
    if results["unmutated copy"] != "baseline-ok":
        print("error: the suite fails on an unmutated copy of the folder")
        return 2
    killed = survived = errors = 0
    for name in names:
        state = results[name]
        if state == "killed":
            killed += 1
            print("killed   %s" % name)
        elif state == "survived":
            survived += 1
            print("survived %s" % name)
        else:
            errors += 1
            print("error    %s: %s" % (name, state))
    print("mutations: %d, killed: %d, survived: %d" % (len(names), killed, survived + errors))
    return 1 if (survived or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
