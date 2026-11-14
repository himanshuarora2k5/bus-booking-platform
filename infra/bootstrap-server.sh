#!/usr/bin/env bash
# Run this ON the new Ubuntu server (after logging in with ssh):   bash infra/bootstrap-server.sh
# Installs Docker and Git, and makes Docker start automatically after every reboot.
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git unzip
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker
echo
echo "Docker installed: $(sudo docker --version)"
echo "IMPORTANT: type 'exit', then log in again with ssh, so the new permissions apply."
