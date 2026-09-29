#!/usr/bin/env bash
# Deploy eSS to Cloud Run. The project and region are fixed here, so a Cloud Shell session
# that points to another project (gcloud config) cannot deploy to the wrong place.
# Usage: ./deploy.sh            (build and deploy)
#        ./deploy.sh migrate    (run database migrations first, then deploy)
set -euo pipefail
PROJECT=espeleosociety
REGION=europe-west3
cd "$(dirname "$0")"
git pull --ff-only
if [[ "${1:-}" == "migrate" ]]; then
  .venv/bin/pip install -q .
  ESS_DATABASE_URL="$(gcloud secrets versions access latest --secret=ess-database-url --project "$PROJECT")" \
    .venv/bin/alembic upgrade head
fi
gcloud run deploy ess --source . --project "$PROJECT" --region "$REGION"
