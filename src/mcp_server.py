"""
mcp_server.py — MCP stdio server wrapping the bandwidth allocation API.

Exposes three tools:
    allocate_bandwidth  — push QoS policer + tc enforcement for a customer
    revoke_bandwidth    — remove both from PE and CE
    verify_bandwidth    — iperf3 UDP throughput probe between two CEs

Run with:
    uv run mcp dev src/mcp_server.py          # interactive inspector
    uv run python -m src.mcp_server           # direct stdio (for Claude Desktop)
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys

# mcp dev loads this file via importlib without package context, so the
# project root isn't on sys.path. Insert it so "src.*" imports resolve.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

from src.bandwidth import (
    allocate_bandwidth as _allocate,
    revoke_bandwidth as _revoke,
    verify_bandwidth as _verify,
)
from src.models import ServiceRequest

logging.basicConfig(level=logging.INFO)

mcp = FastMCP(
    name="srl-bandwidth",
    instructions=(
        "Tools for allocating, revoking, and verifying bandwidth on Nokia SR Linux "
        "provider-edge routers in a ContainerLab topology. "
        "Use allocate_bandwidth to cap a customer's rate, revoke_bandwidth to remove "
        "the cap, and verify_bandwidth to measure actual throughput."
    ),
)


@mcp.tool()
def allocate_bandwidth(
    customer_id: str,
    pe: str,
    subinterface: str,
    mbps: float,
) -> str:
    """Allocate ingress bandwidth for a customer on a PE subinterface.

    Pushes a QoS policer-template to the SR Linux PE via gNMI and applies a
    tc token-bucket filter on the connected CE container for actual enforcement.

    Args:
        customer_id:  Opaque customer identifier (e.g. "orange-labs").
        pe:           PE router name in the ContainerLab topology (e.g. "pe1").
        subinterface: Interface with subinterface index (e.g. "ethernet-1/2.0").
        mbps:         Target rate in Mbps (keep below 10 due to 1000 PPS cap).

    Returns:
        JSON-encoded AllocationResult with success, gnmi_pushed, tc_applied fields.
    """
    req = ServiceRequest(customer_id=customer_id, pe=pe, subinterface=subinterface, mbps=mbps)
    result = _allocate(req)
    return json.dumps(dataclasses.asdict(result))


@mcp.tool()
def revoke_bandwidth(
    customer_id: str,
    pe: str,
    subinterface: str,
) -> str:
    """Remove a bandwidth allocation from a PE subinterface.

    Deletes the gNMI policer config from the SR Linux PE and removes the tc
    rate-limiter from the connected CE container.

    Args:
        customer_id:  Customer identifier (same as used during allocation).
        pe:           PE router name (e.g. "pe1").
        subinterface: Interface with subinterface index (e.g. "ethernet-1/2.0").

    Returns:
        JSON object with status "revoked" and the identifying fields.
    """
    req = ServiceRequest(customer_id=customer_id, pe=pe, subinterface=subinterface, mbps=0.0)
    _revoke(req)
    return json.dumps({"status": "revoked", "customer_id": customer_id, "pe": pe, "subinterface": subinterface})


@mcp.tool()
def verify_bandwidth(
    src_ce: str,
    dst_ce: str,
    expected_mbps: float | None = None,
    tolerance: float = 0.2,
) -> str:
    """Measure throughput between two CE containers and optionally verify a target.

    Runs a 5-second iperf3 UDP probe. Uses sender-side throughput — reliable even
    when the SR Linux container environment causes receiver-side reporting issues.

    Args:
        src_ce:        Source CE name (e.g. "ce1").
        dst_ce:        Destination CE name (e.g. "ce2").
        expected_mbps: If given, verify that measured rate is within tolerance.
        tolerance:     Fraction of expected_mbps allowed as error (default 0.2 = ±20%).

    Returns:
        JSON-encoded VerifyResult with passed, measured_mbps, and message fields.
    """
    result = _verify(src_ce, dst_ce, expected_mbps, tolerance)
    return json.dumps(dataclasses.asdict(result))


if __name__ == "__main__":
    mcp.run(transport="stdio")
