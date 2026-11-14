#!/usr/bin/env bash
# Creates ONE small Ubuntu server on Azure. Only SSH (22), HTTP (80) and HTTPS (443) are reachable.
# Usage:  bash infra/azure-up.sh
# Optional: AZ_LOCATION=southindia AZ_SIZE=Standard_B2s bash infra/azure-up.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v az > /dev/null; then echo "ERROR: Azure CLI ('az') is not installed. See the guide." >&2; exit 1; fi
if ! az account show > /dev/null 2>&1; then echo "ERROR: not logged in. Run: az login --use-device-code" >&2; exit 1; fi

NAME="busbook"
RG="rg-${NAME}"
if [ "$(az group exists -n "$RG")" = "true" ]; then
  echo "ERROR: resource group $RG already exists. Use it, or remove it first: bash infra/azure-down.sh" >&2
  exit 1
fi

LABEL="${NAME}-$(openssl rand -hex 3)"       # public name: <label>.<region>.cloudapp.azure.com
IMAGE="${AZ_IMAGE:-Ubuntu2204}"
LOCATIONS=("${AZ_LOCATION:-centralindia}" southindia southeastasia eastasia uaenorth)
SIZES=("${AZ_SIZE:-Standard_B2s}" Standard_B2ls_v2 Standard_B2als_v2 Standard_D2s_v3 Standard_B1ms)

created=""
for loc in "${LOCATIONS[@]}"; do
  echo ">> trying region: $loc"
  az group create -n "$RG" -l "$loc" -o none
  for size in "${SIZES[@]}"; do
    echo "   trying size: $size ..."
    if az vm create -g "$RG" -n "${NAME}-vm" --image "$IMAGE" --size "$size" \
        --admin-username azureuser --generate-ssh-keys \
        --public-ip-address-dns-name "$LABEL" --os-disk-size-gb 30 -o none 2> /tmp/azure-vm-error.txt; then
      created="$loc $size"
      break 2
    fi
    tail -n 3 /tmp/azure-vm-error.txt
  done
  echo "   nothing worked in $loc, cleaning up and trying the next region ..."
  az group delete -n "$RG" --yes -o none
done

if [ -z "$created" ]; then
  echo "ERROR: could not create a server in any region. Copy the messages above to Claude." >&2
  exit 1
fi

loc="${created% *}"
size="${created#* }"
az vm open-port -g "$RG" -n "${NAME}-vm" --port 80 --priority 900 -o none
az vm open-port -g "$RG" -n "${NAME}-vm" --port 443 --priority 910 -o none
fqdn="${LABEL}.${loc}.cloudapp.azure.com"
ip="$(az vm show -d -g "$RG" -n "${NAME}-vm" --query publicIps -o tsv)"
printf 'RG=%s\nFQDN=%s\nIP=%s\nSIZE=%s\nLOCATION=%s\n' "$RG" "$fqdn" "$ip" "$size" "$loc" > .azure-state

echo
echo "SERVER READY"
echo "  size/region : $size in $loc"
echo "  public name : $fqdn"
echo "  public IP   : $ip"
echo "  log in with : ssh azureuser@$fqdn"
echo "(these details are saved in infra/.azure-state)"
