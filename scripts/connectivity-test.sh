#!/usr/bin/env bash
# Verifies connectivity for both customer pairs and measures unconstrained baseline.
# Run AFTER deploy.sh and push-config.sh, with SR Linux booted (~30-60s after deploy).
set -euo pipefail

CE1=clab-bandwidth-poc-ce1
CE2=clab-bandwidth-poc-ce2
CE3=clab-bandwidth-poc-ce3
CE4=clab-bandwidth-poc-ce4

echo "=== Customer A: CE1 <-> CE2 ==="

echo "1a. Ping CE1 -> CE2 (192.168.2.10)"
docker exec "$CE1" ping -c 3 -W 2 192.168.2.10
echo

echo "1b. Traceroute CE1 -> CE2"
docker exec "$CE1" traceroute -n 192.168.2.10 || true
echo

echo "1c. iperf3 baseline CE1 -> CE2"
docker exec -d "$CE2" iperf3 -s -1 -p 5201
sleep 1
docker exec "$CE1" iperf3 -c 192.168.2.10 -p 5201 -t 5
echo

echo "=== Customer B: CE3 <-> CE4 ==="

echo "2a. Ping CE3 -> CE4 (192.168.4.10)"
docker exec "$CE3" ping -c 3 -W 2 192.168.4.10
echo

echo "2b. Traceroute CE3 -> CE4"
docker exec "$CE3" traceroute -n 192.168.4.10 || true
echo

echo "2c. iperf3 baseline CE3 -> CE4"
docker exec -d "$CE4" iperf3 -s -1 -p 5201
sleep 1
docker exec "$CE3" iperf3 -c 192.168.4.10 -p 5201 -t 5
echo

echo "All connectivity checks done."
