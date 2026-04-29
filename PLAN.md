# PLAN.md — Bandwidth PoC Roadmap

## Phase 0 — Connectivity baseline ✅

**Built:** ContainerLab topology (`topology/bandwidth-poc.clab.yml`) with two Nokia
SR Linux PEs (`pe1`, `pe2`) and two Linux client containers (`ce1`, `ce2`).  Static
routing via the default network-instance gives end-to-end connectivity CE1↔CE2.
Startup configs pushed via `scripts/push-config.sh` (docker cp + sr_cli source).

**Verified:** ping CE1→CE2 succeeds, traceroute shows correct 3-hop path
(CE1 → PE1 → PE2 → CE2), iperf3 baseline lands at ~560 Kbps (well below the
~12 Mbps 1000 PPS ceiling — SR Linux container TCP stalls under load).

---

## Phase 1 — gNMI bandwidth allocation ✅

**Built:** Python package `src/` with:
- `src/bandwidth.py` — public API (`allocate_bandwidth`, `revoke_bandwidth`,
  `verify_bandwidth`) plus `wait_for_gnmi` readiness helper.
- `src/demo.py` — end-to-end demo script: baseline → cap → revoke → restored.

**Config approach that worked:**
```
# Define policer template (sequence-id is list key)
set / qos policer-templates policer-template clab-bw statistics-mode forwarding-focus
set / qos policer-templates policer-template clab-bw policer 10 peak-rate-kbps 5000
set / qos policer-templates policer-template clab-bw policer 10 committed-rate-kbps 5000
set / qos policer-templates policer-template clab-bw policer 10 maximum-burst-size 10000
set / qos policer-templates policer-template clab-bw policer 10 committed-burst-size 10000

# Attach to subinterface (interface-id is list key)
set / qos interfaces interface pe1-e1-2-0 interface-ref interface ethernet-1/2
set / qos interfaces interface pe1-e1-2-0 interface-ref subinterface 0
set / qos interfaces interface pe1-e1-2-0 input policer-templates policer-template clab-bw
```

**gNMI encoding:** dict-style `gc.set(update=[(path, dict)])` — leaf-level tuples
with string values cause JSON parse errors on SR Linux (unquoted enum values).

**Deviations from plan:**
- SR Linux policer does NOT enforce rates in the container software datapath
  (hardware-only feature). Actual enforcement via `tc tbf` on CE container eth1.
- gNMI uses `skip_verify=True` (TLS, no cert verification); `insecure=True` fails.
- iperf3 receiver stats unreliable; switched to sender-side UDP measurement.

**Tested allocation:** 5.0 Mbps target on `pe1 ethernet-1/2.0`.
iperf3 UDP sender measures ~5 Mbps with tc active vs ~20 Mbps probe rate baseline.

---

## Phase 2 — Service-request abstraction (planned)

Grow the topology to 3–5 routers (add a P backbone router, second customer pair).
Introduce a `ServiceRequest` dataclass: `{customer_id, pe, subinterface, mbps}`.
`allocate_bandwidth` and `revoke_bandwidth` accept a `ServiceRequest` object.
The API surface is now what an MCP tool would expose.

---

## Phase 3 — MCP tool wrapping for agent integration (planned)

Wrap `allocate_bandwidth`, `revoke_bandwidth`, and `verify_bandwidth` as MCP tools.
The consumer agent calls these tools instead of calling them directly in Python.
Connect to the broader paper's workflow: agent receives an NFT credential from the
provider, then calls the MCP tool to activate the network service.
