# ContainerLab Bandwidth Allocation PoC

A networking proof-of-concept for the paper *"Autonomous Agent-to-Agent Network
Service Provisioning via Smart-Contract Escrow and Tokenized Authorization"*
(Orange Labs).

This repo demonstrates the **SDN activation step** of that workflow: given a
service request, push a configuration to a Nokia SR Linux provider-edge router
via gNMI and verify the rate-limit takes effect.

## Quick start

### Prerequisites

- Linux host (ContainerLab is natively Linux)
- Docker
- `containerlab` CLI (`bash -c "$(curl -sL https://get.containerlab.dev)"`)
- `uv` Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Phase 0 — Deploy and verify connectivity

```bash
# 1. Deploy the topology (needs sudo for ContainerLab)
bash scripts/deploy.sh

# 2. Wait for SR Linux to boot, then push router configs
sleep 60
bash scripts/push-config.sh

# 3. Verify end-to-end connectivity
bash scripts/connectivity-test.sh
```

Expected: ping CE1→CE2 succeeds, traceroute shows 3 hops.

### Phase 1 — Bandwidth allocation demo

```bash
# Install Python dependencies
uv sync

# Run the demo (no sudo needed)
uv run python -m src.demo
```

The demo:
1. Measures baseline iperf3 throughput
2. Calls `allocate_bandwidth("pe1", "ethernet-1/2.0", 5.0)` — pushes a gNMI QoS
   policer to SR Linux + applies `tc tbf` on CE1's eth1 for enforcement
3. Verifies measured throughput drops to ~5 Mbps
4. Calls `revoke_bandwidth("pe1", "ethernet-1/2.0")` — removes both
5. Verifies throughput returns to baseline

### Teardown

```bash
bash scripts/destroy.sh
```

## Architecture

```
src/bandwidth.py          <- Public API (allocate / revoke / verify)
     |
     |-- gNMI (pygnmi)    -> SR Linux PE: pushes QoS policer-template (intent layer)
     `-- tc tbf            -> CE container: actual traffic enforcement
```

The free SR Linux container image does not enforce QoS policer rates in its
software datapath (hardware-only feature). `tc` on the CE container provides
real enforcement while the gNMI call records the intent on the router — matching
how a real agent would call a network API.

## Notes

- SR Linux containers cap at **1000 PPS** (~12 Mbps at 1500-byte MTU) regardless
  of any QoS config. Keep test allocations below 10 Mbps.
- gNMI credentials: port `57400`, user `admin`, password `NokiaSrl1!`, TLS with
  `skip_verify=True` (self-signed cert).
- Management IPs (`172.20.20.x`) are dynamically assigned — the code discovers
  them at runtime via `docker inspect`.

## Phases

| Phase | Status | Description |
|---|---|---|
| 0 | done | ContainerLab topology, connectivity, iperf3 baseline |
| 1 | done | gNMI bandwidth allocation + tc enforcement + demo |
| 2 | planned | Service-request abstraction, larger topology |
| 3 | planned | MCP tool wrapping for agent integration |
