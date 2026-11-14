#!/usr/bin/env bash
# Creates the .env settings file from .env.example, with fresh random passwords.
# It never overwrites an existing .env.
#
# Usage on your own computer:   bash scripts/make_env.sh
# Usage on a server with a public name:
#   SITE_ADDRESS=myname.centralindia.cloudapp.azure.com HTTP_PORT=80 HTTPS_PORT=443 bash scripts/make_env.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists - leaving it alone." >&2
  exit 1
fi
cp .env.example .env

db_password="$(openssl rand -hex 12)"
grafana_password="$(openssl rand -hex 12)"
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${db_password}|; s|^GRAFANA_PASSWORD=.*|GRAFANA_PASSWORD=${grafana_password}|" .env

if [ -n "${SITE_ADDRESS:-}" ]; then sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=${SITE_ADDRESS}|" .env; fi
if [ -n "${HTTP_PORT:-}" ]; then sed -i "s|^HTTP_PORT=.*|HTTP_PORT=${HTTP_PORT}|" .env; fi
if [ -n "${HTTPS_PORT:-}" ]; then sed -i "s|^HTTPS_PORT=.*|HTTPS_PORT=${HTTPS_PORT}|" .env; fi

echo ".env created with random passwords (never commit it, never show it on screen)."
echo "Dashboard (Grafana) login:  user = admin   password = ${grafana_password}"
