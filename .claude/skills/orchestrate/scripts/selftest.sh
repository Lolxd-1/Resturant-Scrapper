#!/usr/bin/env bash
# shellcheck disable=SC2016 # fixtures below are literal shell code
# selftest.sh: exercises every orch.sh command and failure path in a throwaway repo.
# Run it once per machine (macOS bash 3.2, Linux, Git Bash): bash selftest.sh
set -u
ORCH_SH="$(cd "$(dirname "$0")" && pwd)/orch.sh"
KIT="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t orchtest)
R="$TMP/repo with space"
pass=0; fail=0
trap 'rm -rf "$TMP"' EXIT

o() { bash "$ORCH_SH" "$@"; }
ok() { if "$@"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $CASE"; fi; }
has() { printf '%s\n' "$OUT" | grep -q -- "$1"; }
lacks() { ! has "$1"; }
case_() { CASE=$1; }

mkdir -p "$R/src" "$R/tests" "$R/app/[id]" "$R/.claude/skills"
cd "$R" || exit 1
git init -q . && git config user.email t@example.com && git config user.name selftest
git checkout -q -b main 2>/dev/null || true
printf 'add() { echo $(( $1 + $2 )); }\n' > src/math.sh
printf '. src/math.sh\n[ "$(add 2 3)" = 5 ]\n' > tests/test_math.sh
echo page > "app/[id]/page.tsx"
cp -R "$KIT" .claude/skills/orchestrate
git add -A && git commit -qm init
git checkout -q -b orch/selftest

case_ "init"; OUT=$(o init selftest 2>&1)
ok has "initialized"; ok test -f .orchestrator/STATE.md; ok test ! -f .gitignore
ok grep -qx 'logs/' .orchestrator/.gitignore; ok grep -qx '/.claude/worktrees/' .git/info/exclude
ok grep -qx '\* text eol=lf' .orchestrator/.gitattributes
case_ "init refuses an unfinished run"; o init selftest > /dev/null 2>&1; ok test $? -eq 2

awk '{ print } /^## Verify/ { v = 1 } v && /^# build/ { print "bash tests/test_math.sh"; v = 0 }' .orchestrator/PLAN.md > p.tmp && mv p.tmp .orchestrator/PLAN.md
case_ "baseline"; OUT=$(o baseline 2>&1); ok has "baseline exit 0"

cat > .orchestrator/tasks/T01.md <<'EOF'
# T01: sub
## Write-set
- modify: `src/math.sh`
- create: tests/test_sub.sh
- modify: app/[id]/page.tsx
- create: gen/
## Verify
```bash
. src/math.sh
[ "$(sub 5 3)" = 2 ]
```
EOF
awk '/^## Open questions/ { print "- [~] T01 sub — w1"; print "- [ ] T02 later — w2"; print "" } { sub(/^status: recon/, "status: executing"); print }' \
  .orchestrator/STATE.md > s.tmp && mv s.tmp .orchestrator/STATE.md
case_ "dispatch checkpoint + base"; BASE=$(o checkpoint "dispatch T01"); ok test "$(o base T01)" = "$BASE"
case_ "status counts only real task lines"; OUT=$(o status); ok has "1 in progress, 1 todo"

printf 'sub() { echo $(( $1 - $2 )); }\n' >> src/math.sh
echo t > tests/test_sub.sh; echo v2 > "app/[id]/page.tsx"; mkdir -p gen; echo g > gen/out.txt
echo r > .orchestrator/reports/T01.md
git add src tests app gen .orchestrator/reports && git commit -qm "feat: sub"
echo "- note" >> .orchestrator/tasks/T01.md
case_ "gate PASS (bracket path, subtree entry, orchestrator note)"; OUT=$(o gate T01 "$BASE"); ok has "GATE T01: PASS"
o checkpoint "note T01" > /dev/null
case_ "orchestrator checkpoint is not tamper"; OUT=$(o gate T01 "$BASE"); ok has "PASS"

echo x > README.md && git add README.md && git commit -qm docs
case_ "scope"; OUT=$(o gate T01 "$BASE"); ok has "SCOPE:.*README.md"; ok has "FAIL (scope)"
git reset -q --hard HEAD~1

echo "# edit" >> src/math.sh
case_ "dirty"; OUT=$(o gate T01 "$BASE"); ok has "FAIL (dirty)"
git checkout -q -- src/math.sh

sed -i.bak 's/sub 5 3/sub 9 7/' .orchestrator/tasks/T01.md && rm -f .orchestrator/tasks/T01.md.bak
git add .orchestrator/tasks/T01.md && git commit -qm "loosen"
case_ "tamper"; OUT=$(o gate T01 "$BASE"); ok has "TAMPER"
git reset -q --hard HEAD~1

git checkout -q -b other
case_ "branch"; OUT=$(o gate T01 "$BASE"); ok has "FAIL (branch)"
git checkout -q orch/selftest && git branch -q -D other

git branch -q keep && git reset -q --soft "$BASE~1" && git commit -qm rewrite
case_ "history"; OUT=$(o gate T01 "$BASE"); ok has "HISTORY"
git reset -q --hard keep && git branch -q -D keep

printf 'debug() { console.log(1); }\n' >> src/math.sh
git add src/math.sh && git commit -qm wip
case_ "slop warning + verify failure"; OUT=$(o gate T01 "$BASE"); ok has "WARN src/math.sh"; ok has "FAIL (verify)"
case_ "slop command"; OUT=$(o slop "$BASE"); ok has "slop: 1 finding"
git reset -q --hard HEAD~1
git rm -q tests/test_math.sh && git commit -qm rm
case_ "deleted test file"; OUT=$(o slop "$BASE"); ok has "deleted test file: tests/test_math.sh"
git reset -q --hard HEAD~1

case_ "empty dispatch checkpoint"; H=$(git rev-parse HEAD); B2=$(o checkpoint "dispatch T02 T03")
ok test "$B2" != "$H"; ok test "$(o base T03)" = "$B2"; ok test -z "$(git status --porcelain)"

cat > .orchestrator/tasks/T02.md <<'EOF'
# T02: mul
## Write-set
- create: src/mul.sh
## Verify
```bash
test -f src/mul.sh
```
EOF
B3=$(o checkpoint "dispatch T02")
git worktree add -q -b wt-t02 .claude/worktrees/t02 "$B3"
W="$R/.claude/worktrees/t02"
mkdir -p node_modules && ln -s "$R/node_modules" "$W/node_modules"
(cd "$W" && echo 'mul() { :; }' > src/mul.sh && git add src/mul.sh && git commit -qm mul)
case_ "worktree hidden from main checkout"; ok test -z "$(git status --porcelain)"
case_ "worktree gate ignores symlinked deps"; OUT=$(o gate T02 "$B3" "$W"); ok has "GATE T02: PASS"
case_ "executor-side verify in worktree"; OUT=$(cd "$W" && bash .claude/skills/orchestrate/scripts/orch.sh verify T02); ok has "exit 0"
git merge -q --no-ff --no-edit wt-t02
case_ "verify after merge"; OUT=$(o verify T02); ok has "exit 0"
git worktree remove --force "$W" && git branch -q -d wt-t02
case_ "verify-all"; o verify-all > /dev/null; ok test $? -eq 0

sed -i.bak 's/^status: executing/status: done/' .orchestrator/STATE.md && rm -f .orchestrator/STATE.md.bak
o checkpoint "done selftest" > /dev/null
case_ "new run archives the old one"; OUT=$(o init next 2>&1); ok has "archived"
case_ "base is scoped to the current run"; o base T01 > /dev/null 2>&1; ok test $? -eq 2
case_ "outside a repo"; OUT=$(cd "$TMP" && bash "$ORCH_SH" checkpoint x 2>&1); ok has "not inside a git repository"; ok lacks "run init first"

echo "selftest: $pass passed, $fail failed ($(bash --version | head -n 1 | sed 's/ (.*//'); $(git --version); awk: $( (awk --version || awk -W version) 2>/dev/null < /dev/null | head -n 1))"
[ "$fail" -eq 0 ]
