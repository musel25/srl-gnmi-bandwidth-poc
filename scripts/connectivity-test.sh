#!/usr/bin/env bash
# Verifies CE1 <-> CE2 connectivity and measures the unconstrained baseline.
# Run AFTER deploy.sh and AFTER giving SR Linux a moment to boot (~30-60s).
set -euo pipefail

CE1=clab-bandwidth-poc-ce1
CE2=clab-bandwidth-poc-ce2

echo "=== 1. Ping CE1 -> CE2 (192.168.2.10) ==="
docker exec "$CE1" ping -c 3 -W 2 192.168.2.10
echo

echo "=== 2. Traceroute CE1 -> CE2 (should show 2 hops: PE1, then CE2) ==="
docker exec "$CE1" traceroute -n 192.168.2.10 || true
echo

echo "=== 3. iperf3 baseline (5s, no policer applied) ==="
echo "Note: license-less SR Linux datapath caps at ~12 Mbps regardless."
echo "Starting iperf3 server on CE2..."
docker exec -d "$CE2" iperf3 -s -1 -p 5201
sleep 1
echo "Running iperf3 client from CE1..."
docker exec "$CE1" iperf3 -c 192.168.2.10 -p 5201 -t 5
echo
echo "If you saw ~10 Mbps that's the datapath ceiling — Phase 1 will cap it lower."
