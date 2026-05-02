# CLAUDE.md — ContainerLab Bandwidth Allocation PoC

## Project purpose

Research PoC supporting the paper *"Autonomous Agent-to-Agent Network Service
Provisioning via Smart-Contract Escrow and Tokenized Authorization"* (Orange Labs,
Anthony Lambert).  The full paper covers a 6-stage workflow where consumer and
provider AI agents negotiate and activate network services via on-chain escrow and
NFT credentials.  **This repo isolates only the SDN activation step**: given a
service request ("allocate N Mbps to customer X"), push a configuration to the
correct provider-edge router and verify the rate-limit takes effect.  Agents,
smart contracts, and NFTs are out of scope.  The networking API is kept clean so
it can later be wrapped as an MCP tool the agent layer calls.

---

## Topology

```
   192.168.1.0/24                                       192.168.2.0/24
ce1 ─── eth1 ─── e1-2 ┌─────┐ e1-1 ── 10.0.0.0/30 ── e1-1 ┌─────┐ e1-2 ─── eth1 ─── ce2
192.168.1.10          │ pe1 │ 10.0.0.1            10.0.0.2│ pe2 │          192.168.2.10
                      └─────┘                              └─────┘
                    (SR Linux)                            (SR Linux)
```

- **pe1, pe2**: Nokia SR Linux `ixr-d2l` (containerized, free image)
- **ce1, ce2**: Linux containers (`network-multitool` — has iperf3, tc, ping)
- Management network: `172.20.20.0/24` (clab default)

---

## File layout

```
containerlab-pushing/
├── configs/
│   ├── pe1.cfg           # SR Linux PE1 startup config (set-style CLI commands)
│   └── pe2.cfg           # SR Linux PE2 startup config
├── scripts/
│   ├── deploy.sh         # sudo containerlab deploy
│   ├── destroy.sh        # sudo containerlab destroy --cleanup
│   ├── push-config.sh    # push CLI configs to running PEs (docker cp + sr_cli source)
│   └── connectivity-test.sh  # ping + traceroute + iperf3 baseline
├── src/
│   ├── __init__.py
│   ├── bandwidth.py      # Public API: allocate/revoke/verify_bandwidth
│   ├── demo.py           # End-to-end demo script
│   ├── models.py         # ServiceRequest dataclass
│   └── mcp_server.py     # FastMCP stdio server (Phase 3)
├── topology/
│   └── bandwidth-poc.clab.yml
├── pyproject.toml        # uv project (Python 3.13)
├── CLAUDE.md             # ← you are here
└── PLAN.md               # Phase roadmap and progress
```

---

## Critical constraints

| Constraint | Detail |
|---|---|
| **Datapath cap** | License-less SR Linux caps at **1000 PPS** (~12 Mbps at 1500-byte MTU). Keep all test allocations below 10 Mbps. |
| **Policer not enforced** | The `qos policer-templates` config is accepted by the container but **does not shape traffic** in the software datapath. Additionally, SR Linux's data plane reads packets via `AF_PACKET` raw sockets, which fire **before** `tc` ingress qdiscs in the kernel — so PE-side `tc` policing is also bypassed (confirmed: tc shows drops, iperf3 receiver shows 0 loss). `tc tbf` on the **CE container's `eth1` egress** is the actual rate-limiter. |
| **gNMI TLS** | SR Linux uses TLS with a self-signed cert. Use `skip_verify=True` (not `insecure=True` — that fails). |
| **gNMI creds** | Port `57400`, user `admin`, password `NokiaSrl1!` |
| **Dynamic mgmt IPs** | ContainerLab assigns 172.20.20.x at deploy time. Use `docker inspect` to discover — never hardcode. |
| **Boot time** | SR Linux needs ~30–60 s after deploy before gNMI is responsive. Use `wait_for_gnmi()`. |
| **Startup-config** | The clab `startup-config` mechanism is unreliable for SR Linux containers (race condition). Use `scripts/push-config.sh` instead (docker cp + sr_cli source). |

---

## Common commands

```bash
# Deploy the lab (requires sudo)
bash scripts/deploy.sh
sleep 60   # SR Linux boot

# Push router configs to running lab
bash scripts/push-config.sh

# Test connectivity
bash scripts/connectivity-test.sh

# SSH into PE1 interactively
docker exec -it clab-bandwidth-poc-pe1 sr_cli

# View current QoS config on PE1
docker exec clab-bandwidth-poc-pe1 sr_cli "info /qos"

# Run the Phase 2 demo (two simultaneous customers)
uv run python -m srl_bandwidth.demo

# Run the MCP server interactively (opens Inspector in browser)
uv run mcp dev srl_bandwidth/mcp_server.py

# Run the MCP server over stdio (for Claude Desktop / agent integration)
uv run python -m srl_bandwidth.mcp_server

# Destroy the lab
bash scripts/destroy.sh

# Run iperf3 manually (UDP baseline)
docker exec -d clab-bandwidth-poc-ce2 iperf3 -s -1 -p 5201
docker exec clab-bandwidth-poc-ce1 iperf3 -c 192.168.2.10 -p 5201 -t 5 -u -b 20M
```

---

## Python conventions

- **Environment**: `uv` for all dependency management. `uv run python -m srl_bandwidth.demo` to execute.
- **Package**: `src/` is the root package. New phase modules go in `src/`.
- **Logging**: `logging.getLogger(__name__)` in every module. Demo uses `INFO` level.
- **gNMI**: Always use dict-style values in `gc.set(update=[...])` — leaf-level tuples
  with plain string values fail JSON encoding for SR Linux enums.
- **QoS interface-id naming**: `{pe}-e{n}-{m}-{subif}` (e.g., `pe1-e1-2-0`) for the
  `qos/interfaces/interface` list key. This is deterministic so allocate/revoke can
  find and delete each other's entries without querying state.

---

## Gotchas (learned during Phase 1)

1. **`insecure=True` doesn't work** — SR Linux gNMI server requires TLS even in the
   container. Use `skip_verify=True` to connect without cert verification.

2. **String enum values** — passing `('path/to/leaf', 'some-enum-value')` as a tuple
   sends the value unquoted in JSON, causing a parse error on SR Linux. Always wrap
   in a dict: `('path/to/container', {'leaf': 'value'})`.

3. **QoS interface uniqueness** — The `qos/interfaces/interface` list enforces
   uniqueness of `(interface-ref/interface, interface-ref/subinterface)`. If you try
   to create a second entry pointing to the same physical subinterface, SR Linux
   rejects it. Solution: use a deterministic interface-id and delete-before-replace.

4. **iperf3 receiver shows 0** — In the SR Linux container environment, the iperf3
   receiver summary often shows 0 bytes (TCP window collapse or UDP receiver summary
   timing out). Use the **sender-side** `sum_sent.bits_per_second` from the iperf3
   JSON output — it correctly reflects the tc-limited egress throughput.

5. **Startup-config race condition** — ContainerLab tries to push startup-config
   before SR Linux is ready, resulting in `/tmp/clab-overlay-config: No such file`.
   Use `push-config.sh` instead (waits for sr_cli readiness then uses docker cp +
   sr_cli source).

6. **`docker kill` destroys container veth** — Using `docker kill` (not `docker stop`)
   on a CE container breaks its veth pair. Requires lab redeploy to recover.

7. **Shared policer-template name causes `FailedPrecondition` on delete** — SR Linux
   refuses to delete a `policer-template` that is still referenced by any
   `qos/interfaces/interface` entry on that PE. If two customers share the same PE
   and the same template name, revoking one customer's allocation triggers this error
   because the other customer's interface still holds the reference. Fix: name
   templates per-interface — `clab-bw-{iface_id}` (e.g. `clab-bw-pe1-e1-2-0`) —
   so each allocation owns its own independent template. See `_POLICER_TEMPLATE_PREFIX`
   in `src/bandwidth.py`.

---

## Connecting Claude Desktop to the MCP server (Phase 3)

Add the following to your Claude Desktop config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "srl-bandwidth": {
      "command": "uv",
      "args": [
        "--directory", "/home/musel/Github/srl-gnmi-bandwidth-poc",
        "run", "python", "-m", "srl_bandwidth.mcp_server"
      ]
    }
  }
}
```

After restarting Claude Desktop the hammer icon will show three tools:
`allocate_bandwidth`, `revoke_bandwidth`, `verify_bandwidth`.  The ContainerLab
topology must already be deployed and router configs pushed before calling any tool.

---

## Adding a new phase

1. Create `src/phaseN.py` with your module.
2. Add phase entry to `PLAN.md`.
3. If new Python deps needed: `uv add <package>`.
4. If topology changes needed: edit `topology/bandwidth-poc.clab.yml` and update
   `configs/pe*.cfg`. Add new configs for new nodes.
