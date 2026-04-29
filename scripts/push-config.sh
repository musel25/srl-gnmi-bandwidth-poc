#!/usr/bin/env bash
# Push startup configs to running SR Linux PEs.
# Uses: docker cp (copy cfg into container) + sr_cli -e -c -d (candidate + commit).
set -euo pipefail

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

PE1=clab-bandwidth-poc-pe1
PE2=clab-bandwidth-poc-pe2

wait_for_srlinux() {
    local node=$1
    echo "Waiting for $node sr_cli to be ready..."
    for i in $(seq 1 30); do
        if docker exec "$node" sr_cli "info system" >/dev/null 2>&1; then
            echo "  $node is ready."
            return 0
        fi
        sleep 3
    done
    echo "ERROR: $node did not become ready after 90s" >&2
    exit 1
}

push_config() {
    local node=$1
    local cfg=$2
    local remote=/tmp/srl-startup.cfg
    echo "=== Pushing config to $node ==="
    docker cp "$cfg" "$node:$remote"
    docker exec "$node" sr_cli -e -c -d "source $remote"
    echo "  Done."
}

wait_for_srlinux "$PE1"
wait_for_srlinux "$PE2"

push_config "$PE1" "$PROJECT_ROOT/configs/pe1.cfg"
push_config "$PE2" "$PROJECT_ROOT/configs/pe2.cfg"

echo
echo "Config pushed to both PEs. Run scripts/connectivity-test.sh to verify."
