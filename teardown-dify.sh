#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Tear down ONLY the Dify agent engine (the one always-on, billed-while-idle
#  resource). Everything else — Cloud Run, Hosting, Firestore, Storage — is
#  serverless and costs nothing at rest, so it is left completely untouched.
#
#    ./teardown-dify.sh                  # ask first, then destroy
#    ./teardown-dify.sh --yes            # no prompt (for automation)
#    ./teardown-dify.sh --purge-agents   # also delete agent entries from the
#                                        # model registry (they'd otherwise
#                                        # just stay hidden)
#
#  Removes: the Dify VM + its boot disk, static IP, firewall rule, and the
#  dify-vertex service account (and its keys). Your chat history, users,
#  models, uploads and generated images are NOT touched.
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

c_cyan=$'\033[0;36m'; c_green=$'\033[0;32m'; c_yellow=$'\033[0;33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
say()  { echo "${c_cyan}▸${c_off} $1"; }
ok()   { echo "${c_green}✓${c_off} $1"; }
warn() { echo "${c_yellow}!${c_off} $1"; }
die()  { echo "${c_yellow}✗ $1${c_off}"; exit 1; }

ASSUME_YES=0
PURGE_AGENTS=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)       ASSUME_YES=1 ;;
    --purge-agents) PURGE_AGENTS=1 ;;
    *) die "unknown option: $arg (use --yes and/or --purge-agents)" ;;
  esac
done

[[ -f deploy.config ]] || die "deploy.config not found — nothing was deployed from here."
# shellcheck disable=SC1091
source deploy.config
for bin in gcloud terraform; do command -v "$bin" >/dev/null || die "Missing prerequisite: $bin"; done
gcloud auth print-access-token >/dev/null 2>&1 || die "Run: gcloud auth login"

terraform -chdir=infra init -input=false > /dev/null

# ── is there anything to remove? ────────────────────────────────────────────
if ! terraform -chdir=infra state list 2>/dev/null | grep -q 'google_compute_instance.dify'; then
  ok "No Dify VM in Terraform state — nothing to tear down."
  if [[ "${WITH_DIFY:-false}" == "true" ]]; then
    sed -i.bak 's/^WITH_DIFY=.*/WITH_DIFY="false"/' deploy.config && rm -f deploy.config.bak
    ok "Set WITH_DIFY=\"false\" in deploy.config so future deploys skip it."
  fi
  exit 0
fi

DIFY_IP=$(terraform -chdir=infra output -raw dify_url 2>/dev/null || echo "unknown")

echo
echo "════════════════════════════════════════════════════════════"
echo "  ${c_yellow}About to permanently destroy the Dify engine${c_off}"
echo "════════════════════════════════════════════════════════════"
echo "  VM             dify-engine (${REGION}-a) + its boot disk"
echo "  Static IP      $DIFY_IP"
echo "  Firewall       allow-dify-http"
echo "  Service acct   dify-vertex@$PROJECT_ID.iam.gserviceaccount.com"
echo
echo "  ${c_yellow}This is irreversible.${c_off} Agents you forged in the cloud live"
echo "  on that VM and will be gone; re-forge them after a redeploy."
echo
echo "  ${c_dim}Untouched: Cloud Run, Hosting, Firestore (chat history, users,"
echo "  model registry), Storage (uploads + generated images), Auth.${c_off}"
echo "════════════════════════════════════════════════════════════"

if [[ $ASSUME_YES -ne 1 ]]; then
  read -r -p "Type 'destroy' to continue: " reply
  [[ "$reply" == "destroy" ]] || die "Aborted — nothing was changed."
fi

# ── keep Cloud Run on the image it is already running ───────────────────────
# (terraform's image_tag default is "latest", which may not exist; reusing the
#  live tag makes this a Dify-only change.)
CURRENT_IMAGE=$(gcloud run services describe ai-platform-api \
  --region "$REGION" --project "$PROJECT_ID" \
  --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || echo "")
if [[ -n "$CURRENT_IMAGE" ]]; then
  TAG="${CURRENT_IMAGE##*:}"
  say "Preserving the running backend image (tag: $TAG)"
else
  TAG="latest"
  warn "Cloud Run service not found — using image tag 'latest'"
fi

# ── destroy: every Dify resource is count = with_dify ? 1 : 0, so flipping
#    the flag removes them AND drops DIFY_* env vars from Cloud Run in one go
say "Applying with_dify=false (destroys the VM, updates Cloud Run)…"
terraform -chdir=infra apply -input=false -auto-approve \
  -var "project_id=$PROJECT_ID" -var "region=$REGION" \
  -var "admin_emails=$ADMIN_EMAILS" -var "storage_bucket=$STORAGE_BUCKET" \
  -var "with_dify=false" -var "dify_base_url=" -var "image_tag=$TAG"
ok "Dify infrastructure destroyed"

# ── remember the choice so ./deploy.sh doesn't recreate it ─────────────────
sed -i.bak 's/^WITH_DIFY=.*/WITH_DIFY="false"/' deploy.config && rm -f deploy.config.bak
ok "deploy.config now has WITH_DIFY=\"false\""

# ── optional: drop agent entries from the model registry ───────────────────
if [[ $PURGE_AGENTS -eq 1 ]]; then
  # The Firestore SDK lives in the backend venv, not system python.
  PY_BIN="python3"
  [[ -x backend/.venv/bin/python ]] && PY_BIN="backend/.venv/bin/python"
  if ! "$PY_BIN" -c "from google.cloud import firestore" 2>/dev/null; then
    warn "google-cloud-firestore not available to $PY_BIN — skipping agent purge."
    warn "Delete them from the admin panel (MODEL GRID → PURGE) instead."
  else
    say "Purging Dify agent entries from the model registry…"
    "$PY_BIN" - "$PROJECT_ID" <<'PY'
import sys
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

db = firestore.Client(project=sys.argv[1])
gone = 0
for doc in db.collection("models").where(filter=FieldFilter("provider", "==", "dify")).stream():
    doc.reference.delete()
    gone += 1
print(f"  removed {gone} agent entr{'y' if gone == 1 else 'ies'}")
PY
    ok "Registry cleaned"
  fi
else
  echo "  ${c_dim}Agent entries stay in the registry but are auto-hidden while no"
  echo "  engine is reachable. Re-run with --purge-agents to delete them.${c_off}"
fi

echo
echo "════════════════════════════════════════════════════════════"
echo "  ${c_green}Teardown complete — you are back to \$0 idle cost${c_off}"
echo "════════════════════════════════════════════════════════════"
echo "  Still live   ${c_cyan}https://$FIREBASE_SITE.web.app${c_off}"
echo "               chat, history, models, uploads, image gen, admin"
echo "  Gone         the Dify VM (no more hourly billing)"
echo
echo "  Bring agents back later: set WITH_DIFY=\"true\" in deploy.config"
echo "  and run ./deploy.sh — the VM is rebuilt and bootstrapped for you."
echo "════════════════════════════════════════════════════════════"
