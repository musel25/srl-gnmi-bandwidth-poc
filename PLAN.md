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

## Phase 2 — Service-request abstraction ✅

Grow the topology to 3–5 routers (add a P backbone router, second customer pair).
Introduce a `ServiceRequest` dataclass: `{customer_id, pe, subinterface, mbps}`.
`allocate_bandwidth` and `revoke_bandwidth` accept a `ServiceRequest` object.
The API surface is now what an MCP tool would expose.

**Built:**
- `src/models.py` — `ServiceRequest` dataclass (`customer_id`, `pe`, `subinterface`, `mbps`).
- `src/bandwidth.py` — `allocate_bandwidth` and `revoke_bandwidth` updated to accept
  a `ServiceRequest`; `AllocationResult` gains a `customer_id` field; `_CE_DATA_IP`
  and `_PE_SUBIF_TO_CE` extended with ce3/ce4 and ethernet-1/3.0 mappings.
  Policer template name is now per-interface (`clab-bw-{iface_id}`) to avoid
  `FailedPrecondition` gNMI errors when two customers share the same PE.
- `src/demo.py` — rewritten as a Phase 2 demo showing two simultaneous customer
  allocations (`orange-labs` at 5 Mbps on pe1/e1-2, `inria-net` at 3 Mbps on
  pe1/e1-3) with verification and revocation of both.
- Topology expanded from 4 → 7 nodes: added `p1` (SR Linux backbone), `ce3`, `ce4`.
  Backbone split: pe1 — p1 (10.0.0.0/30) — pe2 (10.0.1.0/30) replacing direct link.
- New configs: `configs/p1.cfg`; `pe1.cfg` and `pe2.cfg` updated with e1-3 ports
  and routes via p1.

**Verified (live run):**
- Traceroute shows correct 4-hop path: ce → pe1 → p1 → pe2 → ce
- orange-labs: 5.20 Mbps measured vs 5.0 target — PASS
- inria-net: 3.16 Mbps measured vs 3.0 target — PASS
- Both paths restored to 20.00 Mbps after revoke — PASS

**Key gotcha fixed:**
SR Linux rejects deletion of a policer-template that is still referenced by another
subinterface on the same PE. Fixed by naming templates per-interface:
`clab-bw-{pe}-e{n}-{m}-{subif}` (e.g. `clab-bw-pe1-e1-2-0`) so each allocation
has its own independent template and delete operations never conflict.

---

## Phase 3 — MCP tool wrapping for agent integration (planned)

Wrap `allocate_bandwidth`, `revoke_bandwidth`, and `verify_bandwidth` as MCP tools
using the `mcp` Python SDK (`pip install mcp`).
The consumer agent calls these tools instead of calling them directly in Python.
Connect to the broader paper's workflow: agent receives an NFT credential from the
provider, then calls the MCP tool to activate the network service.

**Suggested tool surface:**
```
allocate_bandwidth(customer_id, pe, subinterface, mbps) → AllocationResult (as JSON)
revoke_bandwidth(customer_id, pe, subinterface) → None
verify_bandwidth(src_ce, dst_ce, expected_mbps?, tolerance?) → VerifyResult (as JSON)
```

**Entry point:** `src/mcp_server.py` — a stdio MCP server wrapping `src/bandwidth.py`.
Test by connecting Claude Desktop or running with `mcp dev src/mcp_server.py`.
