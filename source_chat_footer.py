#!/usr/bin/env python3
"""source-chat-footer: link an HTML page back to the Claude Code session that wrote it.

Four commands in one file:

  hook      a Claude Code PostToolUse hook that reminds the session to add the footer
  add       insert (or replace) the footer on one page
  remove    take the footer off a page before it is shared
  backfill  find the session for older pages in the transcripts and add the footer

The footer holds a path inside the reader's home folder, so every command shares
one set of rules about which pages are left alone (skipped folders, an opt-out
file, an opt-out comment). Standard library only.
"""
import argparse
import calendar
import datetime
import glob
import hashlib
import html
import json
import os
import pathlib
import re
import shlex
import stat
import sys
import tempfile

# Folder names that mark build output, app source and copies of pages that ship
# to other people. A page below any of them is left alone.
SKIP_DIRS = frozenset([
    "node_modules", ".next", "dist", "build", "out", "coverage", ".git",
    "public", "src", "app", "pages", "components", ".vercel", "_site",
    "deploy", ".venv", "venv", "site-packages", ".tox", "vendor", ".cache",
    "worktrees",
])
OPT_OUT_FILE = ".no-source-chat"
OPT_OUT_COMMENT = "<!-- no-source-chat -->"
START_MARK = "<!-- source-chat-footer:start -->"
END_MARK = "<!-- source-chat-footer:end -->"
TEMPLATE_TOKEN = "__SESSION_ID__"
LINKED_ATTR = 'data-source-chat="'

TOKENS = ("__SESSION_ID__", "__TRACE_URL__", "__TRACE_PATH__",
          "__DATE__", "__LABEL__", "__CONFIDENCE__")
TOKEN_RE = re.compile("|".join(re.escape(t) for t in TOKENS))
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}(?::?\d{2})?)?\Z")
HTM_RE = re.compile(rb"\.htm", re.IGNORECASE)
BODY_END_RE = re.compile(r"</body>", re.IGNORECASE)
PROG = "source-chat-footer"


class Refusal(Exception):
    """An expected failure: the message is one line for stderr."""


class UsageError(Exception):
    """A bad command line."""


class Parser(argparse.ArgumentParser):
    """An argument parser that raises instead of exiting, so the hook can stay silent."""

    def error(self, message):
        raise UsageError(message)


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------

def valid_session(value):
    return isinstance(value, str) and SESSION_RE.fullmatch(value) is not None


def home_dir():
    return os.path.expanduser("~")


def config_dir():
    value = os.environ.get("CLAUDE_CONFIG_DIR")
    if value:
        return value
    return os.path.join(home_dir(), ".claude")


def projects_dir():
    return os.path.join(config_dir(), "projects")


def state_dir():
    value = os.environ.get("SOURCE_CHAT_STATE_DIR")
    if value:
        return value
    cache = os.environ.get("XDG_CACHE_HOME")
    if cache:
        return os.path.join(cache, "source-chat-footer")
    return os.path.join(home_dir(), ".cache", "source-chat-footer")


def is_page_name(path):
    return os.path.basename(path).lower().endswith((".html", ".htm"))


def resolve_page(path):
    """The real path of an existing page, or None."""
    real = os.path.realpath(path)
    if is_page_name(real) and os.path.isfile(real):
        return real
    return None


def is_skipped(real, extra=()):
    """True when a folder name on the page's real path is a skipped name."""
    names = set(SKIP_DIRS)
    names.update(extra)
    parts = os.path.dirname(real).split(os.sep)
    return any(part in names for part in parts if part)


def find_opt_out_file(real):
    """The opt-out file in the page's folder or any folder above it, or None."""
    folder = os.path.dirname(real)
    while True:
        candidate = os.path.join(folder, OPT_OUT_FILE)
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent


def page_status(real):
    """Return (status, text). text is None when the page was not decoded."""
    if find_opt_out_file(real) is not None:
        return "opted_out", None
    with open(real, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "not_utf8", None
    if OPT_OUT_COMMENT in text:
        return "opted_out", text
    if TEMPLATE_TOKEN in text:
        return "template", text
    if LINKED_ATTR in text or START_MARK in text:
        return "linked", text
    return "plain", text


def find_transcript(session, hint=None):
    """Find the transcript file of a session, or None.

    The hint wins when it is a file named for the session. Otherwise the newest
    file named for the session in any project folder wins. A hint with another
    name is the last resort.
    """
    name = session + ".jsonl"
    if isinstance(hint, str) and hint:
        if os.path.isfile(hint) and os.path.basename(hint) == name:
            return os.path.abspath(hint)
    pattern = os.path.join(glob.escape(projects_dir()), "*", name)
    matches = [p for p in glob.glob(pattern) if os.path.isfile(p)]
    if matches:
        best = sorted(matches, key=lambda p: (-os.path.getmtime(p), p))[0]
        return os.path.abspath(best)
    if isinstance(hint, str) and hint and os.path.isfile(hint):
        return os.path.abspath(hint)
    return None


def load_template():
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "footer-snippet.html")
    try:
        with open(path, "rb") as fh:
            block = fh.read().decode("utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("cannot read footer-snippet.html next to this script: %s" % type(exc).__name__)
    if not (block.startswith(START_MARK) and block.endswith(END_MARK)
            and all(t in block for t in TOKENS)):
        raise Refusal("footer-snippet.html must start with the start mark, end with the end "
                      "mark and keep all six tokens")
    return block


def render_block(template, session, trace, label, confidence, date):
    """Fill the six tokens in one pass, escaping every value."""
    values = {
        "__SESSION_ID__": session,
        "__TRACE_URL__": pathlib.Path(trace).as_uri(),
        "__TRACE_PATH__": trace,
        "__DATE__": date,
        "__LABEL__": label,
        "__CONFIDENCE__": confidence,
    }
    escaped = dict((k, html.escape(v, quote=True)) for k, v in values.items())
    return TOKEN_RE.sub(lambda m: escaped[m.group(0)], template)


def strip_blocks(text, replacement=""):
    """Remove every block from the start mark through the end mark.

    The newline after a block goes with it. The first block is replaced by
    `replacement`. Returns (new text, number of blocks). Raises Refusal when a
    start mark has no end mark after it.
    """
    out = []
    pos = 0
    count = 0
    while True:
        start = text.find(START_MARK, pos)
        if start < 0:
            break
        end = text.find(END_MARK, start + len(START_MARK))
        if end < 0:
            raise Refusal("the page holds a footer start mark with no end mark after it")
        end += len(END_MARK)
        if text.startswith("\r\n", end):
            end += 2
        elif text.startswith("\n", end):
            end += 1
        out.append(text[pos:start])
        if count == 0:
            out.append(replacement)
        count += 1
        pos = end
    out.append(text[pos:])
    return "".join(out), count


def place_block(text, block):
    """Replace any footer already on the page and insert the new one.

    The block goes before the last closing body tag, or at the end of the text.
    Returns (new text, whether a block was replaced).
    """
    text, count = strip_blocks(text)
    matches = list(BODY_END_RE.finditer(text))
    if matches:
        at = matches[-1].start()
        return text[:at] + block + "\n" + text[at:], count > 0
    if text and not text.endswith("\n"):
        text += "\n"
    return text + block + "\n", count > 0


def write_page(real, text):
    """Write through a temporary file in the same folder, keeping the permission bits."""
    mode = stat.S_IMODE(os.stat(real).st_mode)
    fd, tmp = tempfile.mkstemp(prefix=".source-chat-", suffix=".tmp", dir=os.path.dirname(real))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def local_date(epoch):
    return datetime.date.fromtimestamp(epoch).isoformat()


def parse_time(value, fallback):
    """Epoch seconds of an ISO time string, or `fallback` when it is not usable."""
    if not isinstance(value, str):
        return fallback
    m = TIME_RE.match(value.strip())
    if not m:
        return fallback
    year, month, day, hour, minute, second = [int(m.group(i)) for i in range(1, 7)]
    micro = int(((m.group(7) or "") + "000000")[:6])
    try:
        stamp = datetime.datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return fallback
    offset = 0
    zone = m.group(8)
    if zone and zone not in ("Z", "z"):
        digits = zone[1:].replace(":", "")
        minutes = int(digits[:2]) * 60 + (int(digits[2:4]) if len(digits) > 2 else 0)
        offset = minutes * 60 * (1 if zone[0] == "+" else -1)
    return calendar.timegm(stamp.timetuple()) + micro / 1e6 - offset


def say_error(message):
    sys.stderr.write("%s: %s\n" % (PROG, message))


# ---------------------------------------------------------------------------
# hook
# ---------------------------------------------------------------------------

def marker_path(session, real):
    digest = hashlib.sha256(("%s|%s" % (session, real)).encode("utf-8", "surrogateescape")).hexdigest()
    return os.path.join(state_dir(), digest[:40])


def hook_file_path(obj):
    tool_input = obj.get("tool_input")
    if isinstance(tool_input, dict):
        value = tool_input.get("file_path")
        if isinstance(value, str) and value:
            return value
    tool_response = obj.get("tool_response")
    if isinstance(tool_response, dict):
        value = tool_response.get("filePath")
        if isinstance(value, str) and value:
            return value
    return None


def reminder_text(real, session, trace, status):
    command = " ".join(shlex.quote(part) for part in [
        sys.executable or "python3",
        os.path.abspath(__file__),
        "add", real,
        "--session", session,
        "--transcript", trace,
    ])
    if status == "linked":
        head = "SOURCE-CHAT FOOTER OUT OF DATE: %s\n" % real
        head += ("The footer on this page names an earlier session; "
                 "the command below replaces it with this session.\n")
    else:
        head = "SOURCE-CHAT FOOTER MISSING: %s\n" % real
    lines = [
        head.rstrip("\n"),
        "",
        "This page does not link the Claude Code session that wrote it.",
        "If the page is for the user's own use, run this one command to add the footer:",
        command,
        "",
        "The footer holds a file link to the session transcript, the command that resumes "
        "the session (claude --resume with the session id), the session id and the date.",
        "",
        "Do NOT add the footer to a page that will be published, sent or handed to someone "
        "else, because it holds a path inside the home folder of this machine. For such a "
        "page, do nothing.",
        "To stop these reminders for every page under a folder, create an empty file named "
        ".no-source-chat in that folder.",
    ]
    return "\n".join(lines)


def run_hook(args):
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        return
    if not isinstance(obj, dict):
        return
    session = obj.get("session_id")
    if not valid_session(session):
        return
    path = hook_file_path(obj)
    if path is None:
        return
    real = resolve_page(path)
    if real is None:
        return
    if is_skipped(real, args.skip_dir):
        return
    status, text = page_status(real)
    if status in ("opted_out", "not_utf8", "template"):
        return
    if session in text:
        return
    marker = marker_path(session, real)
    if os.path.exists(marker):
        return
    name = os.path.basename(real)
    trace = find_transcript(session, obj.get("transcript_path"))
    if trace is None:
        print(json.dumps({"systemMessage": (
            "source-chat-footer: no transcript found for session %s, so no footer was "
            "suggested for %s" % (session, name))}))
        return
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(marker, "ab"):
            pass
    except OSError:
        pass
    out = {"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": reminder_text(real, session, trace, status),
    }}
    if not args.quiet:
        out["systemMessage"] = ("source-chat-footer: %s has no source-chat footer; "
                                "asked the session to add one" % name)
    print(json.dumps(out))


def cmd_hook(args):
    try:
        run_hook(args)
    except Exception as exc:  # the hook never blocks a tool call
        print(json.dumps({"systemMessage": "source-chat-footer: hook failed: %s" % type(exc).__name__}))
    return 0


# ---------------------------------------------------------------------------
# add and remove
# ---------------------------------------------------------------------------

def check_date(value):
    if value is None:
        return datetime.date.today().isoformat()
    if DATE_RE.fullmatch(value):
        try:
            datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
            return value
        except ValueError:
            pass
    raise Refusal("--date must be a real date written YYYY-MM-DD, got %r" % value)


def refuse_status(real, status):
    if status == "opted_out":
        found = find_opt_out_file(real)
        if found is not None:
            raise Refusal("%s is opted out by the file %s" % (real, found))
        raise Refusal("%s is opted out by the comment %s" % (real, OPT_OUT_COMMENT))
    if status == "not_utf8":
        raise Refusal("%s is not UTF-8 text, so it was not changed" % real)
    if status == "template":
        raise Refusal("%s holds the token %s, so it is a template and was not changed"
                      % (real, TEMPLATE_TOKEN))


def do_add(args):
    real = resolve_page(args.file)
    if real is None:
        raise Refusal("%s is not an existing .html or .htm file" % args.file)
    if not valid_session(args.session):
        raise Refusal("%r is not a valid session id" % args.session)
    status, text = page_status(real)
    refuse_status(real, status)
    if args.transcript is not None and not os.path.isfile(args.transcript):
        raise Refusal("the transcript %s does not exist" % args.transcript)
    trace = find_transcript(args.session, args.transcript)
    if trace is None:
        raise Refusal("no transcript found for session %s" % args.session)
    date = check_date(args.date)
    template = load_template()
    block = render_block(template, args.session, trace, "Source chat", "wrote", date)
    new_text, replaced = place_block(text, block)
    write_page(real, new_text)
    print("%s %s %s" % ("replaced" if replaced else "added", real, args.session))


def do_remove(args):
    real = resolve_page(args.file)
    if real is None:
        raise Refusal("%s is not an existing .html or .htm file" % args.file)
    with open(real, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal("%s is not UTF-8 text, so it was not changed" % real)
    replacement = "" if OPT_OUT_COMMENT in text else OPT_OUT_COMMENT + "\n"
    new_text, count = strip_blocks(text, replacement)
    if count == 0:
        print("no footer found %s" % real)
        return
    write_page(real, new_text)
    print("removed %s" % real)


def guarded(func, args):
    try:
        func(args)
    except Refusal as exc:
        say_error(str(exc))
        return 2
    except OSError as exc:
        say_error("could not complete: %s" % (exc.strerror or type(exc).__name__))
        return 2
    return 0


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

def collect_transcripts(projects):
    """List (main transcript, session, file to read) for every usable transcript file.

    A main transcript is <projects>/<project>/<session>.jsonl. A helper transcript
    is any .jsonl below <projects>/<project>/<session>/ and counts for that session
    only when the main transcript exists. Everything else is ignored.
    """
    found = []
    for project in sorted(os.listdir(projects)):
        pdir = os.path.join(projects, project)
        if os.path.islink(pdir) or not os.path.isdir(pdir):
            continue
        names = sorted(os.listdir(pdir))
        mains = {}
        for name in names:
            full = os.path.join(pdir, name)
            stem = name[:-len(".jsonl")]
            if (name.endswith(".jsonl") and os.path.isfile(full)
                    and valid_session(stem) and not stem.startswith("agent-")):
                mains[stem] = full
        for stem in sorted(mains):
            found.append((mains[stem], stem, mains[stem]))
        for name in names:
            full = os.path.join(pdir, name)
            if name not in mains or os.path.islink(full) or not os.path.isdir(full):
                continue
            for base, dirs, files in os.walk(full):
                dirs.sort()
                for fname in sorted(files):
                    if fname.endswith(".jsonl"):
                        found.append((mains[name], name, os.path.join(base, fname)))
    return found


def collect_pages(roots, extra_skip):
    """Walk the roots without following symlinked folders.

    Returns (pages, symlink count). pages maps real path to the path as walked.
    """
    pages = {}
    links = 0
    names = set(SKIP_DIRS)
    names.update(extra_skip)
    for root in roots:
        for base, dirs, files in os.walk(os.path.abspath(root)):
            dirs[:] = sorted(d for d in dirs if d not in names)
            for fname in sorted(files):
                if not is_page_name(fname):
                    continue
                full = os.path.join(base, fname)
                if is_skipped(os.path.join(os.path.realpath(base), fname), extra_skip):
                    continue
                if os.path.islink(full):
                    links += 1
                    continue
                if not os.path.isfile(full):
                    continue
                pages.setdefault(os.path.realpath(full), full)
    return pages, links


def scan_transcripts(transcripts, pages):
    """One pass over every transcript file. Returns (writes, mentions).

    Each maps a page's real path to (time, main transcript, session). A write is
    a Write or Edit tool call on the page; the latest one wins. A mention is the
    page's path appearing in a line; the earliest one wins.
    """
    needles = {}
    for real, walked in pages.items():
        for variant in set([walked, real]):
            raw = os.fsencode(variant)
            needles.setdefault(os.path.basename(raw), {}).setdefault(raw, set()).add(real)
    writes = {}
    mentions = {}
    real_cache = {}
    for main, session, path in transcripts:
        try:
            fallback = os.path.getmtime(path)
            fh = open(path, "rb")
        except OSError:
            continue
        with fh:
            for line in fh:
                if not HTM_RE.search(line):
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                stamp = fallback
                if isinstance(obj, dict):
                    stamp = parse_time(obj.get("timestamp"), fallback)
                for real in written_pages(obj, pages, real_cache):
                    best = writes.get(real)
                    if best is None or stamp > best[0] or (stamp == best[0] and main < best[1]):
                        writes[real] = (stamp, main, session)
                for base, variants in needles.items():
                    if base not in line:
                        continue
                    for raw, owners in variants.items():
                        if raw not in line:
                            continue
                        for real in owners:
                            best = mentions.get(real)
                            if best is None or stamp < best[0] or (stamp == best[0] and main < best[1]):
                                mentions[real] = (stamp, main, session)
    return writes, mentions


def written_pages(obj, pages, real_cache):
    """Real paths of known pages that a Write or Edit call in this line names."""
    if not isinstance(obj, dict):
        return []
    message = obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    hits = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") not in ("Write", "Edit"):
            continue
        tool_input = block.get("input")
        target = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        if not isinstance(target, str) or not os.path.isabs(target) or not is_page_name(target):
            continue
        if target not in real_cache:
            real_cache[target] = os.path.realpath(target)
        if real_cache[target] in pages:
            hits.append(real_cache[target])
    return hits


def run_backfill(args):
    roots = args.roots
    for root in roots:
        if not os.path.isdir(root):
            raise Refusal("%s is not an existing folder" % root)
    projects = os.path.abspath(projects_dir())
    if not os.path.isdir(projects):
        raise Refusal("the projects folder %s does not exist" % projects)

    pages, symlinks = collect_pages(roots, args.skip_dir)
    counts = dict(found=len(pages), linked=0, templates=0, opted_out=0, not_utf8=0,
                  symlinks=symlinks, by_write=0, by_mention=0, guesses=0,
                  no_session=0, could_not=0)
    lines = []
    plain = {}
    for real in sorted(pages):
        try:
            status, text = page_status(real)
            mtime = os.stat(real).st_mtime
        except OSError as exc:
            counts["could_not"] += 1
            lines.append("could not read %s: %s" % (real, exc.strerror or type(exc).__name__))
            continue
        if status == "plain":
            plain[real] = (text, mtime)
        elif status == "linked":
            counts["linked"] += 1
        elif status == "template":
            counts["templates"] += 1
        elif status == "opted_out":
            counts["opted_out"] += 1
        else:
            counts["not_utf8"] += 1
            lines.append("not utf-8 %s" % pages[real])

    candidates = dict((r, pages[r]) for r in plain)
    writes, mentions = ({}, {})
    if candidates:
        writes, mentions = scan_transcripts(collect_transcripts(projects), candidates)

    template = load_template() if plain else None
    for real in sorted(plain):
        text, mtime = plain[real]
        walked = pages[real]
        if real in writes:
            tier = "wrote"
            _, main, session = writes[real]
        elif real in mentions:
            tier = "mentioned"
            _, main, session = mentions[real]
            if not args.infer:
                counts["guesses"] += 1
                lines.append("guess %s %s mentioned (a guess, not written; --infer links it)"
                             % (walked, session))
                continue
        else:
            counts["no_session"] += 1
            lines.append("no session %s" % walked)
            continue
        verb = "linked" if args.apply else "would link"
        if args.apply:
            label = "Source chat" if tier == "wrote" else "Source chat (inferred)"
            block = render_block(template, session, main, label, tier, local_date(mtime))
            try:
                # The transcript scan can take a while; a page edited meanwhile is left alone.
                if page_status(real) != ("plain", text):
                    raise Refusal("the page changed while backfill ran; run backfill again")
                new_text, _ = place_block(text, block)
                write_page(real, new_text)
            except (OSError, Refusal) as exc:
                counts["could_not"] += 1
                lines.append("could not write %s: %s" % (walked, getattr(exc, "strerror", None) or exc))
                continue
        counts["by_write" if tier == "wrote" else "by_mention"] += 1
        lines.append("%s %s %s %s" % (verb, walked, session, tier))

    verb = "linked" if args.apply else "would link"
    for line in lines:
        print(line)
    print("summary")
    print("pages found: %d" % counts["found"])
    print("already linked: %d" % counts["linked"])
    print("templates: %d" % counts["templates"])
    print("opted out: %d" % counts["opted_out"])
    print("not UTF-8: %d" % counts["not_utf8"])
    print("symlinks left alone: %d" % counts["symlinks"])
    print("%s by a write: %d" % (verb, counts["by_write"]))
    print("%s by a mention: %d" % (verb, counts["by_mention"]))
    print("guesses not linked: %d" % counts["guesses"])
    print("no session found: %d" % counts["no_session"])
    print("could not write: %d" % counts["could_not"])
    if args.apply:
        print("applied: the footers above were written")
    else:
        print("dry run: nothing was changed; add --apply to write the footers")
    return 1 if counts["could_not"] else 0


def cmd_backfill(args):
    try:
        return run_backfill(args)
    except Refusal as exc:
        say_error(str(exc))
        return 2
    except OSError as exc:
        say_error("could not complete: %s" % (exc.strerror or type(exc).__name__))
        return 2


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def build_parser():
    parser = Parser(prog=PROG, description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", parser_class=Parser)
    sub.required = True

    p = sub.add_parser("hook", help="Claude Code PostToolUse hook; reads one JSON object on stdin")
    p.add_argument("--quiet", action="store_true", help="leave out the routine systemMessage")
    p.add_argument("--skip-dir", action="append", default=[], metavar="NAME",
                   help="also skip pages below a folder with this name (repeatable)")

    p = sub.add_parser("add", help="insert or replace the footer on a page")
    p.add_argument("file")
    p.add_argument("--session", required=True)
    p.add_argument("--transcript")
    p.add_argument("--date")

    p = sub.add_parser("remove", help="take the footer off a page before it is shared")
    p.add_argument("file")

    p = sub.add_parser("backfill", help="add footers to older pages by reading the transcripts")
    p.add_argument("roots", nargs="+", metavar="ROOT")
    p.add_argument("--apply", action="store_true", help="write the footers (default: dry run)")
    p.add_argument("--infer", action="store_true",
                   help="also link pages the transcripts only mention (a guess)")
    p.add_argument("--skip-dir", action="append", default=[], metavar="NAME",
                   help="also skip pages below a folder with this name (repeatable)")
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = build_parser().parse_args(argv)
    except UsageError as exc:
        if argv[:1] == ["hook"]:
            print(json.dumps({"systemMessage": "source-chat-footer: hook failed: UsageError"}))
            return 0
        sys.stderr.write("usage error: %s\n" % exc)
        return 2
    if args.command == "hook":
        return cmd_hook(args)
    if args.command == "add":
        return guarded(do_add, args)
    if args.command == "remove":
        return guarded(do_remove, args)
    return cmd_backfill(args)


if __name__ == "__main__":
    sys.exit(main())
