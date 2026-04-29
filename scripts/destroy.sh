#!/usr/bin/env bash
# Destroys the bandwidth-poc lab and cleans up artifacts.
set -euo pipefail

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$PROJECT_ROOT"

sudo containerlab destroy -t topology/bandwidth-poc.clab.yml --cleanup
