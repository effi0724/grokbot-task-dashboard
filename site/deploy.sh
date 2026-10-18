#!/usr/bin/env bash
# Deploy the dashboard to Cloudflare Pages.
# Required environment variables (never commit the values):
#   CLOUDFLARE_API_TOKEN
#   CLOUDFLARE_ACCOUNT_ID
#   PROJECT_NAME          Pages project name
set -euo pipefail
cd "$(dirname "$0")"
: "${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?Set CLOUDFLARE_ACCOUNT_ID}"
: "${PROJECT_NAME:?Set PROJECT_NAME to your Cloudflare Pages project name}"
command -v wrangler >/dev/null || { echo "Install wrangler first (npm install -g wrangler)"; exit 1; }
wrangler pages deploy public --project-name="$PROJECT_NAME" --commit-dirty=true
