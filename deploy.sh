#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  NEXUS one-command cloud deploy.
#
#    1. cp deploy.config.example deploy.config   (fill it in)
#    2. gcloud auth login && gcloud auth application-default login
#    3. ./deploy.sh
#
#  Deploys: Cloud Run backend + Firebase Hosting UI (+ optional Dify VM),
#  then prints every endpoint. Partial runs: ./deploy.sh backend|frontend
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

c_cyan=$'\033[0;36m'; c_green=$'\033[0;32m'; c_yellow=$'\033[0;33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
say()  { echo "${c_cyan}▸${c_off} $1"; }
ok()   { echo "${c_green}✓${c_off} $1"; }
warn() { echo "${c_yellow}!${c_off} $1"; }
die()  { echo "${c_yellow}✗ $1${c_off}"; exit 1; }

# ── config & prereqs ────────────────────────────────────────────────────────
[[ -f deploy.config ]] || { cp deploy.config.example deploy.config; \
  die "Created deploy.config — edit it with your project settings, then re-run."; }
# shellcheck disable=SC1091
source deploy.config
for v in PROJECT_ID REGION FIREBASE_SITE ADMIN_EMAILS STORAGE_BUCKET; do
  [[ -n "${!v:-}" && "${!v}" != your-* ]] || die "Set $v in deploy.config"
done
for bin in gcloud terraform node npm python3 curl; do
  command -v "$bin" >/dev/null || die "Missing prerequisite: $bin"
done
gcloud auth print-access-token >/dev/null 2>&1 || die "Run: gcloud auth login"

TARGET="${1:-all}"
TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/ai-platform/backend:$TAG"
TF_VARS=(-var "project_id=$PROJECT_ID" -var "region=$REGION" \
         -var "admin_emails=$ADMIN_EMAILS" -var "storage_bucket=$STORAGE_BUCKET" \
         -var "with_dify=${WITH_DIFY:-false}" \
         -var "dify_machine_type=${DIFY_MACHINE_TYPE:-e2-standard-2}")

gapi() { # authed Google REST helper
  curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
       -H "x-goog-user-project: $PROJECT_ID" -H "Content-Type: application/json" "$@"
}

# ── one-time Firebase foundations (idempotent) ──────────────────────────────
ensure_foundations() {
  say "Ensuring Firebase foundations (APIs, Firestore, bucket, Hosting site)…"
  gcloud services enable firebase.googleapis.com identitytoolkit.googleapis.com \
    firestore.googleapis.com firebasestorage.googleapis.com firebasehosting.googleapis.com \
    --project "$PROJECT_ID" --quiet

  gapi "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID" \
    | grep -q '"state": "ACTIVE"' \
    || gapi -X POST "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID:addFirebase" -d '{}' >/dev/null

  gcloud firestore databases describe --database="(default)" --project "$PROJECT_ID" >/dev/null 2>&1 \
    || gcloud firestore databases create --database="(default)" --location="$REGION" \
         --type=firestore-native --project "$PROJECT_ID" --quiet

  gapi -X POST "https://firebasestorage.googleapis.com/v1beta/projects/$PROJECT_ID/defaultBucket" \
    -d "{\"location\":\"$(echo "$REGION" | tr '[:lower:]' '[:upper:]')\"}" >/dev/null 2>&1 || true

  gapi "https://firebasehosting.googleapis.com/v1beta1/projects/$PROJECT_ID/sites/$FIREBASE_SITE" \
    | grep -q defaultUrl \
    || gapi -X POST "https://firebasehosting.googleapis.com/v1beta1/projects/$PROJECT_ID/sites?siteId=$FIREBASE_SITE" >/dev/null

  # Authorize the hosting domain for Google sign-in.
  gapi "https://identitytoolkit.googleapis.com/v2/projects/$PROJECT_ID/config" | python3 - "$FIREBASE_SITE" <<'PY' > /tmp/nexus_domains.json
import json, sys
cfg = json.load(sys.stdin)
domains = cfg.get("authorizedDomains", [])
site = f"{sys.argv[1]}.web.app"
if site not in domains: domains.append(site)
print(json.dumps({"authorizedDomains": domains}))
PY
  gapi -X PATCH \
    "https://identitytoolkit.googleapis.com/v2/projects/$PROJECT_ID/config?updateMask=authorizedDomains" \
    -d @/tmp/nexus_domains.json >/dev/null
  ok "Foundations ready"
}

# ── secrets for the Dify engine ─────────────────────────────────────────────
ensure_dify_secrets() {
  DIFY_EMAIL="admin@nexus.local"
  if DIFY_PASS=$(gcloud secrets versions access latest --secret dify-admin-password \
                   --project "$PROJECT_ID" 2>/dev/null); then
    ok "Dify admin secrets already exist"
  else
    DIFY_PASS=$(openssl rand -base64 18 | tr '+/' 'Aa')
    printf %s "$DIFY_EMAIL" | gcloud secrets versions add dify-admin-email    --project "$PROJECT_ID" --data-file=- >/dev/null
    printf %s "$DIFY_PASS"  | gcloud secrets versions add dify-admin-password --project "$PROJECT_ID" --data-file=- >/dev/null
    ok "Generated Dify admin credentials (stored only in Secret Manager)"
  fi
}

# ── stages ──────────────────────────────────────────────────────────────────
deploy_backend() {
  ensure_foundations
  say "Terraform bootstrap (APIs, registry, secrets, service accounts)…"
  terraform -chdir=infra init -input=false > /dev/null
  terraform -chdir=infra apply -input=false -auto-approve \
    -target=google_project_service.apis \
    -target=google_artifact_registry_repository.backend \
    -target=google_service_account.api \
    -target=google_secret_manager_secret.secrets "${TF_VARS[@]}" > /dev/null
  ok "Bootstrap applied"

  [[ "${WITH_DIFY:-false}" == "true" ]] && ensure_dify_secrets

  say "Building backend image via Cloud Build ($TAG)…"
  gcloud builds submit backend --project "$PROJECT_ID" --region "$REGION" --tag "$IMAGE" --quiet
  ok "Image pushed"

  say "Terraform full apply (Cloud Run rollout$( [[ "${WITH_DIFY:-false}" == "true" ]] && echo " + Dify VM" ))…"
  terraform -chdir=infra apply -input=false -auto-approve -var "image_tag=$TAG" "${TF_VARS[@]}"
  ok "Infra deployed"

  if [[ "${WITH_DIFY:-false}" == "true" ]]; then
    DIFY_URL=$(terraform -chdir=infra output -raw dify_url)
    DIFY_SA=$(terraform -chdir=infra output -raw dify_sa_email)
    say "Bootstrapping Dify at $DIFY_URL (plugins + Gemini access)…"
    KEYFILE=$(mktemp)
    gcloud iam service-accounts keys create "$KEYFILE" --iam-account "$DIFY_SA" \
      --project "$PROJECT_ID" --quiet
    DIFY_ADMIN_EMAIL="$DIFY_EMAIL" DIFY_ADMIN_PASSWORD="$DIFY_PASS" \
      GCP_PROJECT="$PROJECT_ID" GCP_REGION="$REGION" \
      VERTEX_SA_KEY_B64="$(base64 < "$KEYFILE" | tr -d '\n')" \
      python3 scripts/setup_dify.py "$DIFY_URL"
    rm -f "$KEYFILE"
    ok "Dify engine ready"
  fi
}

deploy_frontend() {
  say "Building + deploying frontend to site '$FIREBASE_SITE'…"
  [[ -f frontend/.env.local ]] || warn "frontend/.env.local missing — copy frontend/.env.example and fill in your Firebase web app config first"
  printf '{\n  "projects": { "default": "%s" }\n}\n' "$PROJECT_ID" > frontend/.firebaserc
  python3 - "$FIREBASE_SITE" <<'PY'
import json, sys
cfg = json.load(open("frontend/firebase.json"))
cfg["hosting"]["site"] = sys.argv[1]
json.dump(cfg, open("frontend/firebase.json", "w"), indent=2)
PY
  ( cd frontend && npm install --silent && npm run build ) > /dev/null
  ( cd frontend && npx --yes firebase-tools deploy --only hosting --project "$PROJECT_ID" ) | tail -3
  ok "Hosting deployed"
}

case "$TARGET" in
  backend)  deploy_backend ;;
  frontend) deploy_frontend ;;
  all)      deploy_backend; deploy_frontend ;;
  *) die "usage: ./deploy.sh [backend|frontend|all]" ;;
esac

# ── endpoints summary ───────────────────────────────────────────────────────
RUN_URL=$(terraform -chdir=infra output -raw cloud_run_url 2>/dev/null || echo "n/a")
echo
echo "════════════════════════════════════════════════════════════"
echo "  ${c_green}Deployment complete${c_off}"
echo "════════════════════════════════════════════════════════════"
echo "  Frontend    ${c_cyan}https://$FIREBASE_SITE.web.app${c_off}"
echo "  Backend     ${c_cyan}$RUN_URL${c_off}  ${c_dim}(reached via the frontend's /api/**)${c_off}"
if [[ "${WITH_DIFY:-false}" == "true" ]]; then
  echo "  Dify        ${c_cyan}$(terraform -chdir=infra output -raw dify_url)${c_off}"
  echo "              ${c_dim}login: admin@nexus.local · password:${c_off}"
  echo "              ${c_dim}gcloud secrets versions access latest --secret dify-admin-password --project $PROJECT_ID${c_off}"
else
  echo "  Dify        ${c_dim}not deployed (WITH_DIFY=false) — agents hidden in prod${c_off}"
fi
echo "────────────────────────────────────────────────────────────"
echo "  Smoke test: curl https://$FIREBASE_SITE.web.app/api/healthz"
echo "════════════════════════════════════════════════════════════"
