#!/usr/bin/env bash
# Deletes EVERYTHING that azure-up.sh created (server, disk, network, public address).
# Usage:  bash infra/azure-down.sh
set -euo pipefail
cd "$(dirname "$0")"
RG="rg-busbook"
read -r -p "This DELETES the whole server and its data (resource group $RG). Type YES: " answer
if [ "$answer" != "YES" ]; then echo "cancelled"; exit 1; fi
az group delete -n "$RG" --yes
rm -f .azure-state
echo "deleted. Azure billing for this server has stopped."
