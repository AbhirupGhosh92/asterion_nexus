# =============================================================================
# AI Platform — Terraform Starter
# Provisions: Artifact Registry, Secret Manager, Cloud Run (scale-to-zero),
# dedicated service account with least-privilege IAM.
#
# Usage:
#   cd infra
#   terraform init
#   terraform apply -var="project_id=YOUR_PROJECT" -var="region=us-central1"
# =============================================================================

terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # Recommended: store state in GCS once the bucket exists.
  # backend "gcs" {
  #   bucket = "YOUR_PROJECT-tfstate"
  #   prefix = "ai-platform"
  # }
}

variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run + Artifact Registry"
}

variable "service_name" {
  type    = string
  default = "ai-platform-api"
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Image tag to deploy from Artifact Registry"
}

variable "admin_emails" {
  type        = string
  description = "Comma-separated admin allowlist for the control plane"
}

variable "storage_bucket" {
  type        = string
  description = "Firebase Storage bucket for media uploads / generated images"
}

variable "dify_base_url" {
  type        = string
  default     = ""
  description = "External Dify engine URL. Ignored when with_dify=true; empty = agents hidden."
}

variable "with_dify" {
  type        = bool
  default     = false
  description = "Deploy the Dify agent engine on a small always-on VM (the one non-serverless, billed-while-idle piece)."
}

variable "dify_machine_type" {
  type    = string
  default = "e2-standard-2"
}

locals {
  dify_url     = var.with_dify ? "http://${google_compute_address.dify[0].address}" : var.dify_base_url
  dify_enabled = var.with_dify || var.dify_base_url != ""
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# -----------------------------------------------------------------------------
# APIs
# -----------------------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com", # Vertex AI (LLM + Memory Bank + image gen)
    "iamcredentials.googleapis.com",
    "cloudbuild.googleapis.com",      # gcloud builds submit
    "firestore.googleapis.com",       # chat history + model registry
    "firebasestorage.googleapis.com", # media uploads
    "compute.googleapis.com"          # optional Dify VM
  ])
  service            = each.key
  disable_on_destroy = false
}

# -----------------------------------------------------------------------------
# Artifact Registry — holds the backend container image
# -----------------------------------------------------------------------------
resource "google_artifact_registry_repository" "backend" {
  repository_id = "ai-platform"
  location      = var.region
  format        = "DOCKER"
  description   = "Backend images for the AI platform"

  # Cost control: keep only recent images.
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }

  depends_on = [google_project_service.apis]
}

# -----------------------------------------------------------------------------
# Service account — the ONLY identity the Cloud Run service runs as.
# Least privilege: secrets read + Vertex AI user. Nothing else.
# -----------------------------------------------------------------------------
resource "google_service_account" "api" {
  account_id   = "${var.service_name}-sa"
  display_name = "AI Platform API service account"
}

resource "google_project_iam_member" "api_roles" {
  for_each = toset([
    "roles/aiplatform.user",    # Vertex LLMs, Memory Bank, image generation
    "roles/datastore.user",     # Firestore: history, registry, upload metadata
    "roles/firebaseauth.admin", # admin panel: list users, set tiers, lock accounts
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.api.email}"
}

# Media bucket access (bucket created by Firebase, managed outside Terraform).
resource "google_storage_bucket_iam_member" "media_access" {
  bucket = var.storage_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

# -----------------------------------------------------------------------------
# Secrets — created empty; add versions out-of-band so values never touch
# Terraform state:  echo -n "value" | gcloud secrets versions add <name> --data-file=-
# -----------------------------------------------------------------------------
locals {
  secrets = ["dify-admin-email", "dify-admin-password"]
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(local.secrets)
  secret_id = each.key
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# Grant access per-secret (tighter than project-level secretAccessor).
resource "google_secret_manager_secret_iam_member" "api_access" {
  for_each  = google_secret_manager_secret.secrets
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

# -----------------------------------------------------------------------------
# Cloud Run v2 — scale-to-zero, CPU throttled while idle (cheapest config).
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "api" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL" # required for Firebase Hosting rewrites

  template {
    service_account = google_service_account.api.email

    scaling {
      min_instance_count = 0 # scale-to-zero: pay nothing while idle
      max_instance_count = 3 # cost ceiling for an individual developer
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.backend.repository_id}/backend:${var.image_tag}"

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi" # NeMo Guardrails + LangChain + Vertex SDKs need headroom
        }
        # cpu_idle=true => CPU only allocated during requests (default billing
        # model). Only disable this if you attach a GPU or run background work.
        cpu_idle          = true
        startup_cpu_boost = true # faster cold starts, no idle cost
      }

      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "LLM_PROVIDER"
        value = "vertexai"
      }
      env {
        name  = "ADMIN_EMAILS"
        value = var.admin_emails
      }
      env {
        name  = "STORAGE_BUCKET"
        value = var.storage_bucket
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = "https://${var.project_id}.web.app,https://${var.project_id}.firebaseapp.com"
      }

      # Dify engine wiring — only when an engine exists (VM or external URL;
      # without one, agents are hidden from the model list automatically).
      dynamic "env" {
        for_each = local.dify_enabled ? [1] : []
        content {
          name  = "DIFY_BASE_URL"
          value = local.dify_url
        }
      }
      dynamic "env" {
        for_each = local.dify_enabled ? [1] : []
        content {
          name = "DIFY_ADMIN_EMAIL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["dify-admin-email"].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = local.dify_enabled ? [1] : []
        content {
          name = "DIFY_ADMIN_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["dify-admin-password"].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 5
        period_seconds        = 3
        failure_threshold     = 10
      }
    }

    max_instance_request_concurrency = 40
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.api_access,
  ]
}

# -----------------------------------------------------------------------------
# Invoker policy.
#
# Firebase Hosting rewrites do NOT attach an identity token, so the service
# must allow unauthenticated invocation at the network layer. Application-layer
# auth is enforced in FastAPI by verifying the Firebase ID token on every
# request — nothing works without a valid token.
#
# If you later front this with API Gateway or your own proxy that mints ID
# tokens, replace `allUsers` with that proxy's service account for
# defense-in-depth.
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -----------------------------------------------------------------------------
# Optional Dify agent engine — a small VM running the Dify docker compose
# stack (Postgres/Redis/workers can't scale to zero). Everything else in this
# file is serverless; this is the one always-on, billed-while-idle resource.
# -----------------------------------------------------------------------------
resource "google_compute_address" "dify" {
  count  = var.with_dify ? 1 : 0
  name   = "dify-engine-ip"
  region = var.region
}

resource "google_compute_firewall" "dify_http" {
  count   = var.with_dify ? 1 : 0
  name    = "allow-dify-http"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["80"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["dify-engine"]
}

# Dedicated SA whose key is configured inside Dify so agents can call Gemini.
resource "google_service_account" "dify_vertex" {
  count        = var.with_dify ? 1 : 0
  account_id   = "dify-vertex"
  display_name = "Dify Vertex AI access"
}

resource "google_project_iam_member" "dify_vertex_user" {
  count   = var.with_dify ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.dify_vertex[0].email}"
}

resource "google_compute_instance" "dify" {
  count        = var.with_dify ? 1 : 0
  name         = "dify-engine"
  machine_type = var.dify_machine_type
  zone         = "${var.region}-a"
  tags         = ["dify-engine"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 60
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.dify[0].address
    }
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -e
    if [ ! -d /opt/dify ]; then
      curl -fsSL https://get.docker.com | sh
      git clone --depth 1 https://github.com/langgenius/dify /opt/dify
      cp /opt/dify/docker/.env.example /opt/dify/docker/.env
    fi
    cd /opt/dify/docker && docker compose up -d
  EOT

  depends_on = [google_project_service.apis]
}

output "cloud_run_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "dify_url" {
  value = var.with_dify ? "http://${google_compute_address.dify[0].address}" : var.dify_base_url
}

output "dify_sa_email" {
  value = var.with_dify ? google_service_account.dify_vertex[0].email : ""
}

output "artifact_registry_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.backend.repository_id}"
}

output "service_account_email" {
  value = google_service_account.api.email
}
