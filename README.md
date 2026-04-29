# ContainerLab Bandwidth Allocation PoC

A networking proof-of-concept for the paper *"Autonomous Agent-to-Agent Network
Service Provisioning via Smart-Contract Escrow and Tokenized Authorization"*
(Orange Labs).

This repo demonstrates the **SDN activation step** of that workflow: given a
service request, push a configuration to a Nokia SR Linux provider-edge router
via gNMI, verify the rate-limit takes effect, and expose the whole operation as
MCP tools that an AI agent can call directly.

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

Expected: ping CE1→CE2 succeeds, traceroute shows 4 hops (ce1 → pe1 → p1 → pe2 → ce2).

### Phase 1 & 2 — Bandwidth allocation demo

```bash
# Install Python dependencies
uv sync

# Run the demo (two simultaneous customers)
uv run python -m src.demo
```

The demo:
1. Measures baseline iperf3 throughput for both customer paths
2. Calls `allocate_bandwidth` for `orange-labs` (5 Mbps on pe1/e1-2) and
   `inria-net` (3 Mbps on pe1/e1-3) — pushes gNMI QoS policers + applies
   `tc tbf` on the CE containers for enforcement
3. Verifies measured throughput matches each target (±20%)
4. Revokes both allocations and verifies throughput returns to baseline

### Phase 3 — MCP server (agent integration)

```bash
# Start the MCP inspector (interactive browser UI for testing tools)
uv run mcp dev src/mcp_server.py

# Or run directly over stdio (used by Claude Desktop / agent frameworks)
uv run python -m src.mcp_server
```

The server exposes three tools: `allocate_bandwidth`, `revoke_bandwidth`,
`verify_bandwidth`. See [Connecting to Claude Desktop](#connecting-to-claude-desktop)
below.

### Teardown

```bash
bash scripts/destroy.sh
```

## Architecture

```
Claude Desktop / AI Agent
        │  MCP (stdio)
        ▼
src/mcp_server.py          <- FastMCP server (Phase 3)
        │
src/bandwidth.py           <- Public API (allocate / revoke / verify)
        │
        ├── gNMI (pygnmi)  -> SR Linux PE: pushes QoS policer-template (intent layer)
        └── tc tbf          -> CE container: actual traffic enforcement
```

The free SR Linux container image does not enforce QoS policer rates in its
software datapath (hardware-only feature). `tc` on the CE container provides
real enforcement while the gNMI call records the intent on the router — matching
how a real agent would call a network API.

## Topology

```
 192.168.1.0/24                                         192.168.2.0/24
ce1 ──── pe1 ──── p1 (backbone) ──── pe2 ──── ce2
ce3 ────/                              \──── ce4
 192.168.3.0/24                         192.168.4.0/24
```

Seven nodes: `pe1`, `pe2`, `p1` (SR Linux `ixr-d2l`), `ce1`–`ce4` (Linux,
`network-multitool`). Two independent customer paths share `pe1`.

## Connecting to Claude Desktop

Add the following to your Claude Desktop configuration file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "srl-bandwidth": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/srl-gnmi-bandwidth-poc",
        "run", "python", "-m", "src.mcp_server"
      ]
    }
  }
}
```

After restarting Claude Desktop the hammer icon will show three tools. The
ContainerLab topology must be deployed and router configs pushed before calling
any tool.

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
| 2 | done | ServiceRequest abstraction, 7-node topology, multi-customer demo |
| 3 | done | FastMCP stdio server — `allocate_bandwidth`, `revoke_bandwidth`, `verify_bandwidth` as AI agent tools |
