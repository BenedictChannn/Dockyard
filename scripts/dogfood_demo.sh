#!/usr/bin/env bash
set -euo pipefail

# Dockyard dogfood demo:
# - creates 2 fake repos, 3 branches
# - creates checkpoints
# - shows harbor sorting
# - generates review item trigger
# - prints resume and handoff

ROOT_DIR="$(mktemp -d)"
export DOCKYARD_HOME="${ROOT_DIR}/dockyard_store"

echo "Demo workspace: ${ROOT_DIR}"
echo "Dockyard store: ${DOCKYARD_HOME}"

init_repo() {
  local repo_path="$1"
  mkdir -p "${repo_path}"
  git -C "${repo_path}" init
  git -C "${repo_path}" config user.email "dockyard-demo@example.com"
  git -C "${repo_path}" config user.name "Dockyard Demo"
  echo "# $(basename "${repo_path}")" > "${repo_path}/README.md"
  git -C "${repo_path}" add README.md
  git -C "${repo_path}" commit -m "initial"
}

REPO_A="${ROOT_DIR}/repo-alpha"
REPO_B="${ROOT_DIR}/repo-beta"
init_repo "${REPO_A}"
init_repo "${REPO_B}"

# Repo A / main checkpoint
python3 -m dockyard save \
  --root "${REPO_A}" \
  --no-prompt \
  --objective "Implement baseline CLI scaffolding" \
  --decisions "Typer + Rich + SQLite" \
  --next-step "Add save tests" \
  --risks "Need review for CLI aliases" \
  --command "python3 -m pytest -q" \
  --tests-run --tests-command "python3 -m pytest -q" \
  --build-ok --build-command "python3 -m pip check" \
  --lint-fail --smoke-fail \
  --tag mvp

# Repo A / feature branch with risky path -> auto review
git -C "${REPO_A}" checkout -b hotfix/security-patch
mkdir -p "${REPO_A}/security"
echo "token = 'rotate-me'" > "${REPO_A}/security/auth_guard.py"
python3 -m dockyard save \
  --root "${REPO_A}" \
  --no-prompt \
  --objective "Patch auth guard" \
  --decisions "Add stricter guard checks" \
  --next-step "Run security tests" \
  --risks "Critical path, must review" \
  --command "pytest tests/security -q" \
  --no-tests-run --build-fail --lint-fail --smoke-fail \
  --tag hotfix

# Repo B / main checkpoint
python3 -m dockyard save \
  --root "${REPO_B}" \
  --no-prompt \
  --objective "Prepare docs workflow" \
  --decisions "Keep docs under docs/" \
  --next-step "Write command reference" \
  --risks "Low risk" \
  --command "echo docs ready" \
  --tests-run --tests-command "echo no tests" \
  --build-ok --build-command "echo build ok" \
  --lint-ok --lint-command "echo lint ok" \
  --smoke-ok --smoke-notes "CLI opens" \
  --tag docs

echo
echo "=== Harbor Dashboard ==="
python3 -m dockyard ls

echo
echo "=== Open Reviews ==="
python3 -m dockyard review

echo
echo "=== Resume + Handoff (Repo A hotfix) ==="
(cd "${REPO_A}" && python3 -m dockyard resume --branch hotfix/security-patch --handoff)

echo
echo "Demo complete."
