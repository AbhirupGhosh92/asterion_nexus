#!/usr/bin/env bash
# Apply branch protection and repository security settings for main.
#
# Prerequisites:
#   brew install gh
#   gh auth login
#
# Usage:
#   ./scripts/setup-github-security.sh              # full setup (requires CI on main)
#   ./scripts/setup-github-security.sh --skip-ci    # skip required status checks
#
# Idempotent — safe to re-run after pushing new workflows.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"
RULESET_NAME="MainBranchProtection"
SKIP_CI=0
[[ "${1:-}" == "--skip-ci" ]] && SKIP_CI=1

c_cyan=$'\033[0;36m'; c_green=$'\033[0;32m'; c_yellow=$'\033[0;33m'; c_off=$'\033[0m'
say() { echo "${c_cyan}▸${c_off} $1"; }
ok()  { echo "${c_green}✓${c_off} $1"; }
warn(){ echo "${c_yellow}!${c_off} $1"; }

if ! gh auth status >/dev/null 2>&1; then
  echo "Run: gh auth login" >&2
  exit 1
fi

say "Repository: $REPO"

# ---------------------------------------------------------------------------
# 1. Repository hygiene
# ---------------------------------------------------------------------------
say "Configuring merge and branch settings…"
gh api "repos/$OWNER/$NAME" -X PATCH \
  -f delete_branch_on_merge=true \
  -f allow_update_branch=true \
  -f allow_squash_merge=true \
  -f allow_rebase_merge=true \
  -f allow_merge_commit=false \
  -f allow_auto_merge=false \
  >/dev/null
ok "Squash/rebase merges only; auto-delete merged branches; update-branch enabled"

# ---------------------------------------------------------------------------
# 2. Dependabot alerts + automated security fixes (public repos: free)
# ---------------------------------------------------------------------------
say "Enabling Dependabot vulnerability alerts…"
gh api "repos/$OWNER/$NAME/vulnerability-alerts" -X PUT >/dev/null 2>&1 \
  && ok "Dependabot alerts enabled" \
  || warn "Could not enable alerts (needs admin on repo)"

say "Enabling Dependabot security updates…"
gh api "repos/$OWNER/$NAME/automated-security-fixes" -X PUT >/dev/null 2>&1 \
  && ok "Automated security fixes enabled" \
  || warn "Could not enable automated fixes (needs admin on repo)"

# ---------------------------------------------------------------------------
# 3. Branch ruleset for main (~DEFAULT_BRANCH)
# ---------------------------------------------------------------------------
RULES='[
  {
    "type": "pull_request",
    "parameters": {
      "required_approving_review_count": 1,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": true,
      "require_last_push_approval": false,
      "required_review_thread_resolution": true
    }
  },
  {
    "type": "required_linear_history"
  },
  {
    "type": "deletion"
  },
  {
    "type": "non_fast_forward"
  }
]'

if [[ "$SKIP_CI" -eq 0 ]]; then
  RULES="$(python3 - <<'PY' "$RULES"
import json, sys
rules = json.loads(sys.argv[1])
rules.insert(1, {
    "type": "required_status_checks",
    "parameters": {
        "strict_required_status_checks_policy": True,
        "required_status_checks": [{"context": "ci"}],
    },
})
print(json.dumps(rules))
PY
)"
fi

RULESET_ID="$(gh api "repos/$OWNER/$NAME/rulesets" --jq ".[] | select(.name==\"$RULESET_NAME\") | .id" 2>/dev/null || true)"

PAYLOAD="$(python3 - <<PY
import json
print(json.dumps({
    "name": "$RULESET_NAME",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": json.loads('''$RULES'''),
    "bypass_actors": [],
}))
PY
)"

if [[ -n "$RULESET_ID" ]]; then
  say "Updating ruleset $RULESET_NAME (id=$RULESET_ID)…"
  gh api "repos/$OWNER/$NAME/rulesets/$RULESET_ID" -X PUT --input - <<<"$PAYLOAD" >/dev/null
else
  say "Creating ruleset $RULESET_NAME…"
  gh api "repos/$OWNER/$NAME/rulesets" -X POST --input - <<<"$PAYLOAD" >/dev/null
fi

ok "Main branch ruleset active (PR + review + linear history + no force-push/delete"
if [[ "$SKIP_CI" -eq 0 ]]; then
  ok "Required status check: ci"
else
  warn "Skipped CI status check — re-run without --skip-ci after CI workflow is on main"
fi

echo
ok "Done. Review at: https://github.com/$REPO/settings/rules"
