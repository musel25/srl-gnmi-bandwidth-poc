#!/usr/bin/env bash
# Deploys the bandwidth-poc lab. Run from any directory.
set -euo pipefail

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$PROJECT_ROOT"

if ! command -v containerlab >/dev/null 2>&1; then
    echo "containerlab not found. Install: bash -c \"\$(curl -sL https://get.containerlab.dev)\""
    exit 1
fi

sudo containerlab deploy -t topology/bandwidth-poc.clab.yml

echo
echo "=== Lab deployed. Nodes: ==="
sudo containerlab inspect -t topology/bandwidth-poc.clab.yml
