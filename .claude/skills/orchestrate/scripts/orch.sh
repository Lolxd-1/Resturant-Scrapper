#!/usr/bin/env bash
# orch.sh: deterministic helpers for the `orchestrate` skill.
# Prints short, decision-ready summaries; full command output goes to
# .orchestrator/logs/ so no agent pays tokens for noise.
# Portable: bash 3.2+ (macOS), Linux, Git Bash on Windows. Needs git and awk.
set -u

ORCH=".orchestrator"
SKILL_DIR=$(cd "$(dirname "$0")/.." && pwd)
TAIL_N=${ORCH_TAIL:-30}   # log lines shown per run; the full log path is always printed

die() { printf 'orch: %s\n' "$*" >&2; exit 2; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
root() { git rev-parse --show-toplevel 2>/dev/null || die "not inside a git repository"; }

usage() {
  cat <<'EOF'
usage: orch.sh <command> [args]
  init <slug>              create .orchestrator/ for a new run (archives a finished one)
  status                   one-screen summary: state, next action, open tasks, git
  checkpoint <message>     commit .orchestrator/ only; prints HEAD. "dispatch <IDs>" always commits (that sha is BASE)
  base <ID>                print BASE of the latest "dispatch" checkpoint naming <ID>
  baseline                 run PLAN "Verify (global)" before any change; never fails
  gate <ID> <BASE> [dir]   history, branch, scope, tamper, commit and Verify checks; exit 0 = PASS
  verify <ID> [dir]        run only the task's Verify block
  verify-all               run PLAN "Verify (global)"; exit code is the result
  slop <BASE>              flag debris in lines added since BASE (informational)
EOF
}

# First fenced code block under the first heading that starts with $2.
section_block() {
  awk -v h="$2" '
    index($0, h) == 1 { insec = 1; next }
    insec && /^## / { exit }
    insec && /^```/ { if (inblock) exit; inblock = 1; next }
    inblock { print }
  ' "$1"
}

# Paths listed under "## Write-set" ("- create: path", "- modify: path", ...).
write_set() {
  awk '
    /^## Write-set/ { insec = 1; next }
    insec && /^## / { exit }
    insec && /^[ \t]*[-*][ \t]+/ {
      line = $0
      sub(/^[ \t]*[-*][ \t]+/, "", line)
      sub(/^[A-Za-z]+:[ \t]*/, "", line)
      gsub(/`/, "", line)
      split(line, parts, /[ \t]+/)
      if (parts[1] != "" && parts[1] !~ /^</) print parts[1]
    }
  ' "$1"
}

# Is product path $1 covered by a write-set entry in $2..? Entries match literally (so
# "app/[id]/page.tsx" works); a trailing "/" allows the subtree; "*" is a wildcard.
in_scope() {
  f=$1; shift
  for e in "$@"; do
    [ "$f" = "$e" ] && return 0
    case $e in
      */) case $f in "$e"*) return 0 ;; esac ;;
      *'*'*)
        pat=$(printf '%s' "$e" | sed 's/[][?\\]/\\&/g')
        # shellcheck disable=SC2254 # deliberate: "*" in a write-set entry is a wildcard
        case $f in $pat) return 0 ;; esac ;;
    esac
  done
  return 1
}

# Uncommitted paths in dir $1 outside .orchestrator/, one per line (both sides of a rename).
# Untracked symlinks are skipped: worktree.symlinkDirectories links such as node_modules look like that.
dirty_files() {
  git -C "$1" -c core.quotepath=off status --porcelain --untracked-files=all 2>/dev/null |
  while IFS= read -r line; do
    rest=${line#???}
    while [ -n "$rest" ]; do
      case $rest in
        *' -> '*) p=${rest%% -> *}; rest=${rest#* -> } ;;
        *) p=$rest; rest="" ;;
      esac
      p=${p#\"}; p=${p%\"}
      case $p in "$ORCH"/*) continue ;; esac
      case $line in '?? '*) if [ -L "$1/${p%/}" ]; then continue; fi ;; esac
      printf '%s\n' "$p"
    done
  done
}

# Product paths changed in dir $1 since BASE $2: committed plus uncommitted, unique.
changed_files() {
  {
    git -C "$1" -c core.quotepath=off diff --name-only --no-renames "$2" HEAD -- . ":(exclude)$ORCH"
    dirty_files "$1"
  } | sed 's/^"\(.*\)"$/\1/' | sort -u
}

# Commits since BASE, not made by orch.sh, that changed a brief or the plan.
tampered() {
  git -C "$1" log --format='%h %s' "$2..HEAD" -- "$ORCH/tasks" "$ORCH/PLAN.md" | grep -v '^[0-9a-f]* chore(orch): ' | tr '\n' ';'
}

# Lines added since BASE (outside .orchestrator/) that usually mean debris, plus deleted test files.
# Prints at most $3 findings (0 = all), then "slop: N finding(s)".
slop_scan() {
  {
    git -C "$1" -c core.quotepath=off diff -U0 --no-color "$2" HEAD -- . ":(exclude)$ORCH" | awk '
      BEGIN {
        p = "(TODO|FIXME|XXX|HACK)([^A-Za-z]|$)"
        p = p "|console\\.(log|debug|trace)\\("
        p = p "|(^|[^A-Za-z_])debugger([^A-Za-z_]|$)"
        p = p "|pdb\\.set_trace|breakpoint\\(\\)|binding\\.pry"
        p = p "|(it|describe|test|context)\\.only\\("
        p = p "|(it|describe|test)\\.skip\\(|(^|[^A-Za-z_])x(it|describe)\\("
        p = p "|@pytest\\.mark\\.skip|t\\.Skip\\(|@Disabled|@Ignore"
        p = p "|eslint-disable|@ts-ignore|@ts-nocheck|as any([^A-Za-z_]|$)"
        p = p "|#[ \t]*type:[ \t]*ignore|#[ \t]*noqa|//[ \t]*nolint"
        p = p "|except[^:]*:[ \t]*pass|catch[ \t]*(\\([^)]*\\))?[ \t]*\\{[ \t]*\\}"
      }
      /^\+\+\+ / { file = $0; sub(/^\+\+\+ (b\/)?/, "", file); next }
      /^@@/ { s = $0; sub(/^@@ -[0-9,]+ \+/, "", s); sub(/[^0-9].*$/, "", s); ln = s + 0; next }
      /^\+/ {
        text = substr($0, 2)
        if (file != "/dev/null" && text ~ p) printf "%s:%d: %s\n", file, ln, text
        ln++
      }
    '
    git -C "$1" -c core.quotepath=off diff --name-status "$2" HEAD -- . ":(exclude)$ORCH" | awk -F'\t' '
      $1 == "D" && ($2 ~ /(^|\/)(tests?|__tests__|spec)\// || $2 ~ /[._-](test|spec)\.[A-Za-z]+$/) {
        print "deleted test file: " $2
      }
    '
  } | awk -v max="${3:-0}" '
    { n++; if (max == 0 || n <= max) print }
    END { printf "slop: %d finding(s)%s\n", n, (max > 0 && n > max) ? " (showing " max "; run: orch.sh slop <BASE>)" : "" }
  '
}

# Run the fenced block under heading $2 of file $1 inside dir $3; log as $4.
run_block() {
  rb_block=$(section_block "$1" "$2")
  rb_root=$(root) || exit 2
  if ! printf '%s\n' "$rb_block" | grep -v '^[[:space:]]*#' | grep -q -v '^[[:space:]]*$'; then
    echo "orch: no commands in the fenced block under '$2' in ${1#"$rb_root"/}"
    return 3
  fi
  mkdir -p "$rb_root/$ORCH/logs"
  rb_log="$rb_root/$ORCH/logs/$4-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
  echo "run: '$2' of ${1#"$rb_root"/} · log: ${rb_log#"$rb_root"/}"
  rb_tmp=$(mktemp 2>/dev/null || mktemp -t orch)
  printf 'set -e -o pipefail\n%s\n' "$rb_block" > "$rb_tmp"
  ( cd "$3" && bash "$rb_tmp" < /dev/null ) > "$rb_log" 2>&1
  rb_rc=$?
  rm -f "$rb_tmp"
  tail -n "$TAIL_N" "$rb_log"
  printf -- '--- exit %s\n' "$rb_rc"
  return "$rb_rc"
}

# Keep run debris out of `git status` without touching the user's files:
# .orchestrator/.gitignore and .gitattributes (committed with the run) and the repo-local exclude file.
ensure_excludes() {
  if [ -d "$1/$ORCH" ]; then
    grep -qxF 'logs/' "$1/$ORCH/.gitignore" 2>/dev/null || printf 'logs/\n' >> "$1/$ORCH/.gitignore"
    # Run state is parsed by awk and shared across machines: keep LF everywhere.
    [ -f "$1/$ORCH/.gitattributes" ] || printf '* text eol=lf\n' > "$1/$ORCH/.gitattributes"
  fi
  ex=$(git -C "$1" rev-parse --git-path info/exclude 2>/dev/null) || return 0
  case $ex in /*|[A-Za-z]:*) ;; *) ex="$1/$ex" ;; esac
  if ! grep -qxF '/.claude/worktrees/' "$ex" 2>/dev/null; then
    mkdir -p "$(dirname "$ex")" && printf '/.claude/worktrees/\n' >> "$ex"
  fi
  return 0
}

sed_escape() { printf '%s' "$1" | sed 's/[&|\\]/\\&/g'; }

cmd_init() {
  slug=${1:-}
  [ -n "$slug" ] || die "usage: init <slug>"
  case $slug in
    *[!a-z0-9-]*|-*|*-) die "slug must use lowercase letters, digits and inner hyphens" ;;
  esac
  r=$(root) || exit 2; d="$r/$ORCH"
  git -C "$r" rev-parse -q --verify HEAD > /dev/null || die "repository has no commits; make an initial commit first"
  if [ -f "$d/STATE.md" ]; then
    if grep -q '^status:[[:space:]]*done' "$d/STATE.md"; then
      old=$(awk -F':[ \t]*' '/^run:/ { print $2; exit }' "$d/STATE.md")
      arch="$d/archive/${old:-run}-$(date -u +%Y%m%d%H%M%S)"
      mkdir -p "$arch"
      for f in PLAN.md STATE.md LEDGER.md tasks reports recon; do
        if [ -e "$d/$f" ]; then mv "$d/$f" "$arch/"; fi
      done
      echo "archived finished run to ${arch#"$r"/}"
    else
      die "an unfinished run exists ($ORCH/STATE.md). Resume it, or set its status to done first."
    fi
  fi
  mkdir -p "$d/tasks" "$d/reports" "$d/recon" "$d/logs"
  ensure_excludes "$r"
  br=$(git -C "$r" rev-parse --abbrev-ref HEAD)
  sha=$(git -C "$r" rev-parse HEAD)
  short=$(git -C "$r" rev-parse --short HEAD)
  t=$(now)
  for f in STATE.md PLAN.md; do
    sed -e "s|<slug>|$slug|g" -e "s|<branch>|$(sed_escape "$br")|g" -e "s|<sha>|$sha|g" -e "s|<UTC time>|$t|g" \
      "$SKILL_DIR/assets/$f" > "$d/$f"
  done
  {
    echo "# LEDGER (append-only, one line per event)"
    echo "<!-- format: - <UTC time> <event>. Rulings: \"Ruling: <decision> — <why> — <cost if wrong>\" -->"
    echo "- $t init run=$slug branch=$br base=$short"
  } > "$d/LEDGER.md"
  case $br in
    main|master|trunk|develop|HEAD) echo "WARNING: on '$br'. Work on a feature branch: git switch -c orch/$slug" ;;
  esac
  nd=$(dirty_files "$r" | wc -l | tr -d ' ')
  if [ "$nd" != 0 ]; then
    echo "WARNING: $nd uncommitted path(s) outside $ORCH/, e.g. $(dirty_files "$r" | head -n 3 | tr '\n' ' ')"
    echo "  Gates count these as DIRTY. Commit them (the kit files too) before dispatching; ask the user about their own work."
  fi
  echo "initialized $ORCH/ for run '$slug' on $br@$short"
  echo "next: fill PLAN.md 'Verify (global)', then run: orch.sh baseline"
}

cmd_status() {
  r=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "orch: not inside a git repository"; return 0; }
  st="$r/$ORCH/STATE.md"
  if [ -f "$st" ]; then
    awk '
      /^(run|branch|run-base|status|updated):/ { print; next }
      /^## NEXT ACTION/ { na = 1; print; next }
      /^## / { na = 0; tasks = ($0 ~ /^## Tasks/); next }
      na && NF { print }
      tasks && /^- \[/ {
        k = substr($0, 4, 1); c[k]++
        if (k != "x") open = open "\n  " $0
      }
      END {
        printf "tasks: %d done, %d in progress, %d todo, %d blocked, %d dropped\n", c["x"], c["~"], c[" "], c["!"], c["-"]
        if (open != "") print "open:" open
      }
    ' "$st"
  else
    echo "NO ACTIVE RUN (no $ORCH/STATE.md)"
  fi
  printf 'git: %s @ %s · uncommitted outside %s: %s · extra worktrees: %s\n' \
    "$(git -C "$r" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')" \
    "$(git -C "$r" rev-parse --short HEAD 2>/dev/null || echo none)" \
    "$ORCH/" \
    "$(dirty_files "$r" | wc -l | tr -d ' ')" \
    "$(($(git -C "$r" worktree list | wc -l) - 1))"
  return 0
}

cmd_checkpoint() {
  msg=${*:-bookkeeping}
  r=$(root) || exit 2
  [ -d "$r/$ORCH" ] || die "no $ORCH/ directory; run init first"
  git -C "$r" add -A -- "$ORCH" || die "git add failed"
  # --no-verify: bookkeeping-only commits must not be blocked or rewritten by project hooks.
  if ! git -C "$r" diff --cached --quiet -- "$ORCH"; then
    out=$(git -C "$r" commit -q --no-verify -m "chore(orch): $msg" -- "$ORCH" 2>&1) || die "git commit failed: $out"
  else
    case $msg in
      dispatch\ *)
        # An empty commit without touching the index, so BASE is always findable with `orch.sh base`.
        new=$(git -C "$r" commit-tree "HEAD^{tree}" -p HEAD -m "chore(orch): $msg") || die "git commit-tree failed"
        git -C "$r" update-ref -m "orch: $msg" HEAD "$new" "$(git -C "$r" rev-parse HEAD)" || die "git update-ref failed"
        ;;
    esac
  fi
  git -C "$r" rev-parse HEAD
}

cmd_base() {
  id=${1:-}
  [ -n "$id" ] || die "usage: base <TASK_ID>"
  r=$(root) || exit 2
  # Only this run's history: task IDs repeat across runs.
  range=HEAD
  rbase=$(awk -F':[ \t]*' '/^run-base:/ { print $2; exit }' "$r/$ORCH/STATE.md" 2>/dev/null)
  if [ -n "$rbase" ] && git -C "$r" rev-parse -q --verify "$rbase^{commit}" > /dev/null; then range="$rbase..HEAD"; fi
  sha=$(git -C "$r" log --format='%H %s' --grep='^chore(orch): dispatch ' "$range" | awk -v id="$id" '
    { for (i = 4; i <= NF; i++) if ($i == id) { print $1; exit } }')
  [ -n "$sha" ] || die "no 'dispatch' checkpoint names $id"
  echo "$sha"
}

cmd_baseline() {
  r=$(root) || exit 2
  [ -f "$r/$ORCH/PLAN.md" ] || die "missing $ORCH/PLAN.md; run init and fill 'Verify (global)' first"
  tmp_before=$(mktemp 2>/dev/null || mktemp -t orch)
  tmp_after=$(mktemp 2>/dev/null || mktemp -t orch)
  dirty_files "$r" | sort -u > "$tmp_before"
  run_block "$r/$ORCH/PLAN.md" "## Verify" "$r" baseline
  rc=$?
  dirty_files "$r" | sort -u > "$tmp_after"
  new=$(comm -13 "$tmp_before" "$tmp_after")
  rm -f "$tmp_before" "$tmp_after"
  echo "baseline exit $rc: record pass/fail counts and pre-existing failures in STATE.md > Baseline"
  if [ -n "$new" ]; then
    echo "NOTE: the verify commands created or changed these paths, which every gate would count as DIRTY:"
    printf '%s\n' "$new" | head -n 10 | sed 's/^/  /'
    echo "  Ignore generated output locally: append patterns to $(git -C "$r" rev-parse --git-path info/exclude); restore changed tracked files."
  fi
  return 0
}

cmd_verify_all() {
  r=$(root) || exit 2
  [ -f "$r/$ORCH/PLAN.md" ] || die "missing $ORCH/PLAN.md"
  run_block "$r/$ORCH/PLAN.md" "## Verify" "$r" verify-all
}

cmd_verify() {
  id=${1:-}
  [ -n "$id" ] || die "usage: verify <TASK_ID> [dir]"
  r=$(root) || exit 2
  [ -f "$r/$ORCH/tasks/$id.md" ] || die "brief not found: $ORCH/tasks/$id.md"
  run_block "$r/$ORCH/tasks/$id.md" "## Verify" "${2:-$r}" "$id-verify"
}

cmd_gate() {
  id=${1:-}; base=${2:-}
  { [ -n "$id" ] && [ -n "$base" ]; } || die "usage: gate <TASK_ID> <BASE> [worktree-dir]"
  r=$(root) || exit 2
  dir=${3:-$r}
  [ -d "$dir" ] || die "directory not found: $dir"
  dir=$(cd "$dir" && pwd -P); rp=$(cd "$r" && pwd -P)
  brief="$r/$ORCH/tasks/$id.md"
  [ -f "$brief" ] || die "brief not found: $ORCH/tasks/$id.md (if HEAD moved, see: git reflog -5)"
  git -C "$dir" rev-parse -q --verify "$base^{commit}" > /dev/null || die "BASE $base not found in $dir"
  ensure_excludes "$dir"

  set --
  while IFS= read -r e; do
    if [ -n "$e" ]; then set -- "$@" "$e"; fi
  done <<EOF
$(write_set "$brief")
EOF
  [ $# -gt 0 ] || die "no paths under '## Write-set' in $ORCH/tasks/$id.md"

  commits=$(git -C "$dir" rev-list --count "$base..HEAD")
  nfiles=0; extra=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    nfiles=$((nfiles + 1))
    in_scope "$f" "$@" || extra="$extra $f"
  done <<EOF
$(changed_files "$dir" "$base")
EOF
  echo "== gate $id · base $(git -C "$dir" rev-parse --short "$base") · head $(git -C "$dir" rev-parse --short HEAD) · commits $commits · files $nfiles"

  fails=""
  if ! git -C "$dir" merge-base --is-ancestor "$base" HEAD; then
    echo "HISTORY: BASE is not an ancestor of HEAD (history rewritten or HEAD moved)"; fails="$fails history"
  fi
  if [ "$dir" = "$rp" ]; then
    want=$(awk -F':[ \t]*' '/^branch:/ { print $2; exit }' "$r/$ORCH/STATE.md" 2>/dev/null)
    cur=$(git -C "$r" rev-parse --abbrev-ref HEAD)
    if [ -n "$want" ] && [ "$want" != "$cur" ]; then
      echo "BRANCH: checkout is on '$cur' but the run branch is '$want'"; fails="$fails branch"
    fi
  fi
  if [ -n "$extra" ]; then echo "SCOPE: changed outside the write-set:$extra"; fails="$fails scope"; fi
  tm=$(tampered "$dir" "$base")
  if [ -n "$tm" ]; then echo "TAMPER: non-orchestrator commit(s) changed a brief or PLAN.md: $tm"; fails="$fails tamper"; fi
  nd=$(dirty_files "$dir" | wc -l | tr -d ' ')
  if [ "$nd" != 0 ]; then echo "DIRTY: $nd uncommitted path(s) outside $ORCH/; the executor must commit its work"; fails="$fails dirty"; fi
  if [ "$commits" = 0 ]; then echo "WARN: no commits since BASE"; fi
  sl=$(slop_scan "$dir" "$base" 8)
  case $sl in *"slop: 0 finding"*) ;; *) printf '%s\n' "$sl" | sed 's/^/WARN /' ;; esac

  run_block "$brief" "## Verify" "$dir" "$id" || fails="$fails verify"
  if [ -z "$fails" ]; then
    echo "GATE $id: PASS"
    return 0
  fi
  echo "GATE $id: FAIL ($(printf '%s' "${fails# }" | tr ' ' ','))"
  return 1
}

cmd_slop() {
  base=${1:-}
  [ -n "$base" ] || die "usage: slop <BASE>"
  r=$(root) || exit 2
  git -C "$r" rev-parse -q --verify "$base^{commit}" > /dev/null || die "BASE $base not found"
  slop_scan "$r" "$base" 0
}

cmd=${1:-help}
[ $# -gt 0 ] && shift
case $cmd in
  init|status|checkpoint|base|baseline|gate|verify|verify-all|slop)
    if r0=$(git rev-parse --show-toplevel 2>/dev/null); then ensure_excludes "$r0"; fi ;;
esac
case $cmd in
  init) cmd_init ${1+"$@"} ;;
  status) cmd_status ;;
  checkpoint) cmd_checkpoint ${1+"$@"} ;;
  base) cmd_base ${1+"$@"} ;;
  baseline) cmd_baseline ;;
  gate) cmd_gate ${1+"$@"} ;;
  verify) cmd_verify ${1+"$@"} ;;
  verify-all) cmd_verify_all ;;
  slop) cmd_slop ${1+"$@"} ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
