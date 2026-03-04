#!/bin/bash
# Destroy a Vast.ai instance.
# Usage:
#   ./destroy.sh              — lists running instances and prompts for ID
#   ./destroy.sh <instance_id> — destroys that instance directly

set -e

API_KEY=$(python3 -c "from config import CONFIG; print(CONFIG.get('vast_api_key',''))" 2>/dev/null)
if [[ -z "$API_KEY" ]]; then
    echo "ERROR: vast_api_key not set in config_local.py"
    exit 1
fi

BASE="https://console.vast.ai/api/v0"

list_instances() {
    curl -sf -H "Authorization: Bearer $API_KEY" "$BASE/instances/" | \
        python3 -c "
import json, sys
data = json.load(sys.stdin)
instances = data.get('instances', [])
if not instances:
    print('No running instances.')
    sys.exit(0)
print(f'{'ID':<12} {'Status':<12} {'GPU':<28} {'\$/hr':<8} SSH')
print('-' * 80)
for i in instances:
    gpu = f\"{i.get('gpu_name','?')} x{i.get('num_gpus',1)}\"
    ssh = f\"{i.get('ssh_host','')}:{i.get('ssh_port','')}\" if i.get('ssh_host') else '—'
    print(f\"{i['id']:<12} {(i.get('actual_status') or i.get('cur_state','?')):<12} {gpu:<28} \${i.get('dph_total',0):.3f}   {ssh}\")
"
}

destroy_instance() {
    local ID=$1
    echo "==> Destroying instance $ID..."
    RESULT=$(curl -sf -X DELETE \
        -H "Authorization: Bearer $API_KEY" \
        "$BASE/instances/$ID/")
    echo "$RESULT"
    echo "==> Done. Instance $ID has been destroyed."
}

if [[ -n "$1" ]]; then
    destroy_instance "$1"
else
    echo "==> Your running instances:"
    list_instances
    echo ""
    read -p "Enter instance ID to destroy (or q to quit): " CHOICE
    [[ "$CHOICE" == "q" || -z "$CHOICE" ]] && echo "Aborted." && exit 0
    echo ""
    read -p "Destroy instance $CHOICE? This is irreversible. [y/N] " CONFIRM
    [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && echo "Aborted." && exit 0
    destroy_instance "$CHOICE"
fi
