#!/usr/bin/env bash
# Demo of the four commands, run against an invented session in a temporary folder.
# It touches nothing outside that folder and removes it when it ends.
# Usage: bash examples/demo.sh        (set PYTHON=/path/to/python3 to pick the interpreter)
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(dirname "$HERE")"
PYBIN="$("${PYTHON:-python3}" -c 'import sys; print(sys.executable)')" || exit 1
TOOL="$REPO/source_chat_footer.py"
SESSION="11111111-2222-4333-8444-555555555555"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/source-chat-demo.XXXXXX")" || exit 1
WORK="$(cd "$WORK" && pwd -P)"
trap 'command rm -rf "$WORK"' EXIT

main() {
  export HOME="$WORK/home"
  export CLAUDE_CONFIG_DIR="$WORK/home/.claude"
  export SOURCE_CHAT_STATE_DIR="$WORK/state"
  unset XDG_CACHE_HOME
  export PYTHONDONTWRITEBYTECODE=1

  SITE="$WORK/site"
  PROJECT="$CLAUDE_CONFIG_DIR/projects/-tmp-demo-site"
  TRACE="$PROJECT/$SESSION.jsonl"
  mkdir -p "$SITE/shared" "$PROJECT" "$HOME"

  for name in report notes orphan; do
    printf '<html>\n<body>\n<h1>%s</h1>\n</body>\n</html>\n' "$name" > "$SITE/$name.html"
  done
  printf '<html>\n<body>\n<h1>shared</h1>\n</body>\n</html>\n' > "$SITE/shared/index.html"
  : > "$SITE/shared/.no-source-chat"
  for name in report notes orphan; do touch -t 202601150900 "$SITE/$name.html"; done
  touch -t 202601150900 "$SITE/shared/index.html"

  # An invented transcript: one Write of report.html and one Read that mentions notes.html.
  {
    printf '{"type":"user","timestamp":"2026-01-15T09:00:00Z","message":{"role":"user","content":"make a report"}}\n'
    printf '{"type":"assistant","timestamp":"2026-01-15T09:01:00Z","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Write","input":{"file_path":"%s","content":"report"}}]}}\n' "$SITE/report.html"
    printf '{"type":"assistant","timestamp":"2026-01-15T09:02:00Z","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Read","input":{"file_path":"%s"}}]}}\n' "$SITE/notes.html"
  } > "$TRACE"

  echo "## 1. The hook runs after Claude Code writes report.html"
  HOOK_INPUT="$(printf '{"session_id":"%s","transcript_path":"%s","hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$SESSION" "$TRACE" "$SITE/report.html")"
  HOOK_OUT="$(printf '%s' "$HOOK_INPUT" | "$PYBIN" "$TOOL" hook)"
  printf '%s\n' "$HOOK_OUT" | "$PYBIN" -m json.tool
  echo

  echo "## 2. Run the command the reminder printed"
  # The printed command is split into words with shlex and run as an argument list.
  ARGS=()
  while IFS= read -r -d '' word; do ARGS+=("$word"); done < <(
    printf '%s' "$HOOK_OUT" | "$PYBIN" -c '
import json, shlex, sys
text = json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"]
line = [l for l in text.split("\n") if l.startswith(sys.argv[1]) and " add " in l][0]
sys.stdout.write("".join(w + "\0" for w in shlex.split(line)))' "$PYBIN"
  )
  ARGS+=(--date 2026-01-15)
  printf '$'
  printf ' %q' "${ARGS[@]}"
  echo
  "${ARGS[@]}"
  echo

  echo "## 3. The hook runs again on the same page and stays silent"
  AGAIN="$(printf '%s' "$HOOK_INPUT" | "$PYBIN" "$TOOL" hook)"
  if [ -z "$AGAIN" ]; then echo "(no output)"; else echo "$AGAIN"; fi
  echo

  echo "## 4. backfill, dry run"
  "$PYBIN" "$TOOL" backfill "$SITE"
  echo

  echo "## 5. backfill --apply --infer"
  "$PYBIN" "$TOOL" backfill "$SITE" --apply --infer
  echo

  echo "## 6. The footer lines on notes.html"
  grep -E 'data-source-chat=|<a href=|<code>claude --resume|generated 2' "$SITE/notes.html"
  echo

  echo "## 7. remove, before sharing the page"
  "$PYBIN" "$TOOL" remove "$SITE/notes.html"
  tail -n 3 "$SITE/notes.html"
}

main 2>&1 | sed -e "s|$WORK|/tmp/demo|g" -e "s|$REPO|REPO|g" -e "s|$PYBIN|python3|g"
exit "${PIPESTATUS[0]}"
