# source-chat-footer

source-chat-footer puts a small footer on the HTML pages that Claude Code writes for you. The footer links to the session transcript on your disk, shows the `claude --resume` command that reopens the session, and gives the session id and the date. It is for people who have Claude Code write reports, dashboards and notes for their own use and later want to know which session produced a page.

It is one Python file with four commands (`hook`, `add`, `remove`, `backfill`), plus the footer template `footer-snippet.html`, which must stay in the same folder as the script: `add`, and `backfill` when it has a page to link, refuse to run without it. It uses only the Python standard library and makes no network request.

## What you get

This is the output of `bash examples/demo.sh`, which runs all four commands against an invented session in a temporary folder:

```
## 1. The hook runs after Claude Code writes report.html
{
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "SOURCE-CHAT FOOTER MISSING: /tmp/demo/site/report.html\n\nThis page does not link the Claude Code session that wrote it.\nIf the page is for the user's own use, run this one command to add the footer:\npython3 REPO/source_chat_footer.py add /tmp/demo/site/report.html --session 11111111-2222-4333-8444-555555555555 --transcript /tmp/demo/home/.claude/projects/-tmp-demo-site/11111111-2222-4333-8444-555555555555.jsonl\n\nThe footer holds a file link to the session transcript, the command that resumes the session (claude --resume with the session id), the session id and the date.\n\nDo NOT add the footer to a page that will be published, sent or handed to someone else, because it holds a path inside the home folder of this machine. For such a page, do nothing.\nTo stop these reminders for every page under a folder, create an empty file named .no-source-chat in that folder."
    },
    "systemMessage": "source-chat-footer: report.html has no source-chat footer; asked the session to add one"
}

## 2. Run the command the reminder printed
$ python3 REPO/source_chat_footer.py add /tmp/demo/site/report.html --session 11111111-2222-4333-8444-555555555555 --transcript /tmp/demo/home/.claude/projects/-tmp-demo-site/11111111-2222-4333-8444-555555555555.jsonl --date 2026-01-15
added /tmp/demo/site/report.html 11111111-2222-4333-8444-555555555555

## 3. The hook runs again on the same page and stays silent
(no output)

## 4. backfill, dry run
guess /tmp/demo/site/notes.html 11111111-2222-4333-8444-555555555555 mentioned (a guess, not written; --infer links it)
no session /tmp/demo/site/orphan.html
summary
pages found: 4
already linked: 1
templates: 0
opted out: 1
not UTF-8: 0
symlinks left alone: 0
would link by a write: 0
would link by a mention: 0
guesses not linked: 1
no session found: 1
could not write: 0
dry run: nothing was changed; add --apply to write the footers

## 5. backfill --apply --infer
linked /tmp/demo/site/notes.html 11111111-2222-4333-8444-555555555555 mentioned
no session /tmp/demo/site/orphan.html
summary
pages found: 4
already linked: 1
templates: 0
opted out: 1
not UTF-8: 0
symlinks left alone: 0
linked by a write: 0
linked by a mention: 1
guesses not linked: 0
no session found: 1
could not write: 0
applied: the footers above were written

## 6. The footer lines on notes.html
<footer class="source-chat" data-source-chat="11111111-2222-4333-8444-555555555555" data-link-confidence="mentioned">
    <a href="file:///tmp/demo/home/.claude/projects/-tmp-demo-site/11111111-2222-4333-8444-555555555555.jsonl">/tmp/demo/home/.claude/projects/-tmp-demo-site/11111111-2222-4333-8444-555555555555.jsonl</a>
    <code>claude --resume 11111111-2222-4333-8444-555555555555</code>
    <span>session 11111111-2222-4333-8444-555555555555</span><span>generated 2026-01-15</span>

## 7. remove, before sharing the page
removed /tmp/demo/site/notes.html
<!-- no-source-chat -->
</body>
</html>
```

On a page, the footer is a thin rule at the bottom with small monospace text in three rows: the transcript link, the resume command with a copy button, and the session id with the date. It takes its colours from the page it sits on and becomes fully opaque on hover.

## Quick start

```
git clone <this repository>
cd source-chat-footer
bash examples/demo.sh
```

You need `bash` and Python 3.9. The demo builds an invented project in a temporary folder, points `HOME`, `CLAUDE_CONFIG_DIR` and `SOURCE_CHAT_STATE_DIR` into it, and removes it when it ends, so nothing outside that folder is read or written. Set `PYTHON=/path/to/python3` to choose the interpreter. The output has seven parts:

1. The hook runs after Claude Code writes `report.html`. It prints a JSON reminder for the session, with the exact `add` command to run.
2. The command from the reminder is run. The page now carries the footer.
3. The hook runs again on the same page and prints nothing, because the page is already linked.
4. `backfill` as a dry run. It finds `notes.html`, which the transcript only mentions, and reports it as a guess. It reports `orphan.html` as having no session. It skips the page under the folder that holds `.no-source-chat`.
5. `backfill --apply --infer` writes the guess.
6. The footer lines on `notes.html`: the session id, the transcript link, the resume command and the date.
7. `remove` takes the footer off `notes.html` and leaves `<!-- no-source-chat -->` in its place.

## Turn on the hook

The hook makes Claude Code remind the session to add the footer after it writes or edits a page. Put this in `.claude/settings.json` (inside your home folder for every project, or inside a project folder for that project only), and replace the path with the absolute path of `source_chat_footer.py`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/source_chat_footer.py hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

When Claude Code writes an HTML page, the hook reads the event on standard input. If the page has no footer, the session receives a note (the `additionalContext` in the demo output) that names the page and prints the one `add` command to run, and you see a one-line message. If the page has a footer that names an earlier session, the note is headed `SOURCE-CHAT FOOTER OUT OF DATE` and its `add` command replaces that footer with one for this session. The note also says not to add the footer to a page that will be published or sent. The reminder appears once per page per session. The hook never blocks a tool call and always exits 0.

Options: `--quiet` leaves out the one-line message you would see, and `--skip-dir NAME` (repeatable) adds folder names to the skip list.

## The four commands

```
source_chat_footer.py hook [--quiet] [--skip-dir NAME ...]
source_chat_footer.py add FILE --session ID [--transcript PATH] [--date YYYY-MM-DD]
source_chat_footer.py remove FILE
source_chat_footer.py backfill ROOT [ROOT ...] [--apply] [--infer] [--skip-dir NAME ...]
```

`hook` reads one Claude Code PostToolUse event on standard input. It always exits 0. It prints nothing when there is nothing to say: the event is not a JSON object or has no valid session id or file path, the file is not an HTML page, the page is in a skipped folder, the page is opted out, is not UTF-8 or is a template, the page text contains this session's id anywhere, or this session was already reminded about this page. When no transcript can be found for the session it prints a message and suggests nothing.

`add` writes the footer into one page and prints `added` or `replaced`, the real path and the session id. It exits 0 on success. It exits 2, with one line on stderr and the file unchanged, when the file is not a page, the session id is not valid, the page is opted out, is not UTF-8 or is a template, the transcript is missing, the date is not a real date, or the page holds a start mark with no end mark. A template is any page that contains the literal text `__SESSION_ID__`, such as a copy of `footer-snippet.html` or a page that quotes that token; no command stamps one, and `backfill` counts them under `templates`. If the page already holds a footer it is replaced. The block goes before the last `</body>`, or at the end of the text when there is none. Running the same command twice leaves identical bytes. A symlinked page is changed at its real file.

```
$ python3 source_chat_footer.py add report.html --session 11111111-2222-4333-8444-555555555555 --date 2026-01-15
added /tmp/demo/site/report.html 11111111-2222-4333-8444-555555555555
```

`remove` takes every footer block off a page and leaves `<!-- no-source-chat -->` where the first one was. It prints `removed` and the real path, or `no footer found` and the real path when there was nothing to remove. It exits 0 in both cases and exits 2 when the file is not a page, is not UTF-8 or holds a start mark with no end mark.

```
$ python3 source_chat_footer.py remove notes.html
removed /tmp/demo/site/notes.html
```

`backfill` finds pages under the given folders and links them to the sessions that wrote them. Without `--apply` it changes nothing. It exits 0 when it ran (also when there was nothing to link), 1 when it ran and at least one page could not be read or written (the others are still linked; both kinds are counted under `could not write`), and 2 when it could not run (a root is not a folder, or the projects folder does not exist). See "Stamp older pages" below.

```
$ python3 source_chat_footer.py backfill ~/reports --apply
```

## Pages you share

The footer holds a path inside your home folder and a session id. A page you publish or send must not carry it. These measures make it hard to leave the footer on by accident:

- The skip list. A page is skipped by every command that scans or reminds when any folder name on its real path is one of: `node_modules`, `.next`, `dist`, `build`, `out`, `coverage`, `.git`, `public`, `src`, `app`, `pages`, `components`, `.vercel`, `_site`, `deploy`, `.venv`, `venv`, `site-packages`, `.tox`, `vendor`, `.cache`, `worktrees`. Add more names with `--skip-dir`.
- The `.no-source-chat` file. An empty file with this name opts out every page in its folder and in the folders below it. The hook and `backfill` leave those pages alone, and `add` refuses them.
- The comment. A page that contains `<!-- no-source-chat -->` is opted out in the same way, on its own.
- `remove`. Run it on a page before you share it. It strips the footer and leaves the comment above in its place, so the footer is not added back by a later reminder or backfill. To undo that, delete the comment line from the page and run `add` again.

## Stamp older pages

`backfill` reads the transcripts in the `projects` folder inside your Claude Code config folder (the `.claude` folder in your home folder, or the folder named by `CLAUDE_CONFIG_DIR`) and decides, for each page that has no footer, which session to link. There are two tiers:

- Write tier. A transcript line shows a `Write` or `Edit` call on the page. If several sessions wrote it, the one with the latest line timestamp wins. This is reliable and is always written with `--apply`.
- Mention tier. No write was found, but a transcript line contains the page's path. The earliest session that mentions it wins. A mention is a guess: the session may only have read the page or listed it. A guess is reported and not written unless you add `--infer`, and then the footer is labelled `Source chat (inferred)`.

Pages with neither are reported as `no session`. Helper transcripts that a session spawned are credited to the session that started them, and the footer links that session's main transcript. Run `backfill` without `--apply` first. The footer date is the page's own modification date. The summary at the end prints every count, zeros included, and the last line says whether it was a dry run.

## Change the look

Edit `footer-snippet.html`. It is the block that `add` fills in. Keep the first line (the start mark), the last line (the end mark) and the six tokens: `__SESSION_ID__`, `__TRACE_URL__`, `__TRACE_PATH__`, `__DATE__`, `__LABEL__` and `__CONFIDENCE__`. `add`, and `backfill` when it has a page to link, refuse to run with a template that lost a mark or a token, and `remove` and `add` find an existing block by its two marks.

## Tests

Run these from the folder that holds `source_chat_footer.py`:

```
python3 -m unittest discover -s tests
python3 tests/mutate.py
```

The first command runs 141 tests. The second runs the whole suite on an unchanged temporary copy of the folder and on 41 deliberate breakages of the tool, each in its own fresh temporary copy, four copies at a time. It reports `killed` for a breakage when some test fails or the suite runs past 900 seconds. If the suite fails on the unchanged copy, it says so after every run has finished and exits 2. A breakage whose text does not appear exactly once in the tool is reported as an error and counted as survived. The run exits 1 if any breakage survives, so it proves that the tests fail when the code they cover is wrong. The last line of its output is `mutations: N, killed: N, survived: N`.

## Limits

- The transcript layout and the hook input were checked on Claude Code 2.1.326 on macOS. Other versions may differ.
- When a subagent wrote the page, the hook input on that version carried the parent session's id, so the footer names the session you can resume.
- The footer names the session given to the last `add` or `backfill --apply` that wrote it. When a later session writes the page, the hook reminds that session once, and the footer changes only when it runs the `add` command from the reminder.
- The skip list is checked against every folder on a page's real path, the folders above your project included. Every page under a folder such as `~/src`, `~/app` or `~/public` is skipped by the hook and by `backfill` without a message, and there is no option that takes a name off the list.
- `backfill --apply` reads each page again just before it writes. A page that changed while the transcripts were scanned is left as it is and counted under `could not write`, and the run exits 1; run it again to link that page.
- Pages written by a shell command or a script are not seen by the hook. `backfill` finds them only if a transcript mentions the page.
- The write tier counts only `Write` and `Edit` calls that give an absolute path. A `MultiEdit` call, or a call that gives a relative path, is not counted as a write, and the `Edit|Write` matcher in the settings example does not run the hook after a `MultiEdit` call.
- The hook and `backfill` skip a page when any folder on its path is on the skip list, and that includes the temporary folder. If your temporary folder sits under such a folder (for example `/build/tmp` or `~/.cache/tmp`), the demo output and many tests fail; set `TMPDIR` to another folder to run them.
- The write tier matches by path, so a page that was moved or renamed after it was written is not matched.
- The write tier counts every Write or Edit call that names the page, a call that failed included, so a session whose write failed can still be named as the writer.
- The mention tier looks for the page's path as plain text, so a line that names a longer path holding it, such as `/x/a/report.html` or `/a/report.html.bak`, counts as a mention of `/a/report.html`.
- A path that holds a double quote or a backslash is not matched by the mention tier.
- Claude Code deletes old transcripts after its retention period. After that the link is dead and the session cannot be resumed.
- A browser does not follow a `file://` link from a page served over http. The transcript link works when the page is opened from disk, and the resume command works either way.
- The hook leaves one empty marker file per page per session in the state folder (`SOURCE_CHAT_STATE_DIR`, else `source-chat-footer` inside `XDG_CACHE_HOME`, else `.cache/source-chat-footer` in your home folder). You can delete them at any time.
- The tests and the demo were run on macOS 27.2.1 on Apple silicon with Python 3.9.6, and the demo also with bash 3.2.57. They were not run on Linux or Windows, and not on any Python version other than 3.9.6.

## License

MIT. See `LICENSE`.

## Built at San Diego AI Studio

source-chat-footer comes out of San Diego AI Studio, the builders' community in San Diego where builders show the systems they run. See what people are building at https://sandiegoaistudio.com/projects.
