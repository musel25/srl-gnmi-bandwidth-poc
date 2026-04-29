"""
bandwidth.py — SR Linux gNMI bandwidth allocation for the ContainerLab PoC.

Public API:
    allocate_bandwidth(request: ServiceRequest) -> AllocationResult
    revoke_bandwidth(request: ServiceRequest) -> None
    verify_bandwidth(src_ce, dst_ce, expected_mbps, tolerance) -> VerifyResult

Architecture:
    1. gNMI (pygnmi) pushes a QoS policer-template to the SR Linux PE — this is
       the "intent" layer and matches how a real agent would call a router API.
    2. Linux tc (token-bucket filter) applied inside the CE container provides
       actual traffic enforcement, since the free SR Linux container image does
       not enforce policer rates in its software datapath (1000 PPS ceiling only).
    3. iperf3 UDP sender-side throughput is used for verification: tc on CE1's
       eth1 egress means the sender itself is rate-limited, giving a reliable
       reading regardless of receiver-side reporting issues in the container env.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from pygnmi.client import gNMIclient

from src.models import ServiceRequest

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

GNMI_PORT = 57400
GNMI_USERNAME = "admin"
GNMI_PASSWORD = "NokiaSrl1!"

_CONTAINER_PREFIX = "clab-bandwidth-poc-"

# Prefix for per-interface policer template names. Full name: clab-bw-{iface_id}
# (e.g. clab-bw-pe1-e1-2-0). One template per subinterface prevents the
# FailedPrecondition error that occurs when a shared template is still referenced
# by another interface during delete-before-replace.
_POLICER_TEMPLATE_PREFIX = "clab-bw"
_POLICER_SEQ = 10

# Data-plane IPs of CE containers (set by containerlab exec in topology file)
_CE_DATA_IP = {
    "ce1": "192.168.1.10",
    "ce2": "192.168.2.10",
    "ce3": "192.168.3.10",
    "ce4": "192.168.4.10",
}

# CE container that is attached to each (PE, subinterface) pair — used for tc
_PE_SUBIF_TO_CE = {
    ("pe1", "ethernet-1/2.0"): "ce1",
    ("pe2", "ethernet-1/2.0"): "ce2",
    ("pe1", "ethernet-1/3.0"): "ce3",
    ("pe2", "ethernet-1/3.0"): "ce4",
}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    """Returned by allocate_bandwidth."""
    success: bool
    customer_id: str
    pe: str
    subinterface: str
    mbps: float
    gnmi_pushed: bool
    tc_applied: bool
    message: str = ""


@dataclass
class VerifyResult:
    """Returned by verify_bandwidth."""
    passed: bool
    measured_mbps: float
    expected_mbps: Optional[float]
    tolerance: float
    message: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _container(node: str) -> str:
    return f"{_CONTAINER_PREFIX}{node}"


def _mgmt_ip(node: str) -> str:
    """Return the 172.20.20.x management IP of a clab node."""
    out = subprocess.check_output(
        ["docker", "inspect", _container(node)], text=True
    )
    for net in json.loads(out)[0]["NetworkSettings"]["Networks"].values():
        ip = net.get("IPAddress", "")
        if ip.startswith("172.20.20."):
            return ip
    raise RuntimeError(f"No management IP found for node '{node}'")


def _gnmi(node: str) -> gNMIclient:
    ip = _mgmt_ip(node)
    logger.debug("gNMI target %s → %s:%d", node, ip, GNMI_PORT)
    return gNMIclient(
        target=(ip, GNMI_PORT),
        username=GNMI_USERNAME,
        password=GNMI_PASSWORD,
        skip_verify=True,
    )


def _qos_iface_id(pe: str, iface: str, subif_idx: int) -> str:
    """Deterministic QoS interface-id key: pe1-e1-2-0 for ethernet-1/2.0."""
    sanitized = iface.replace("ethernet-", "e").replace("/", "-")
    return f"{pe}-{sanitized}-{subif_idx}"


def _gnmi_push_policer(pe: str, iface: str, subif_idx: int, rate_kbps: int) -> None:
    """
    Push a QoS policer-template to *pe* and attach it to *iface*.*subif_idx*.

    Uses two gNMI Set RPCs: one to define the template, one to attach it.
    Delete-before-replace ensures idempotency regardless of prior state.
    """
    iface_id = _qos_iface_id(pe, iface, subif_idx)
    tpl = f"{_POLICER_TEMPLATE_PREFIX}-{iface_id}"
    burst = max(10_000, rate_kbps * 125 // 10)  # ~0.1 s burst at CIR

    with _gnmi(pe) as gc:
        # Remove any stale entries for this interface (idempotency)
        try:
            gc.set(delete=[
                f"/qos/interfaces/interface[interface-id={iface_id}]",
                f"/qos/policer-templates/policer-template[name={tpl}]",
            ])
        except Exception:
            pass  # may not exist on first call

        logger.info("gNMI Set: policer-template %s → %d kbps on %s/%s.%d",
                    tpl, rate_kbps, pe, iface, subif_idx)

        gc.set(update=[
            (f"/qos/policer-templates/policer-template[name={tpl}]", {
                "statistics-mode": "forwarding-focus",
                "policer": [{
                    "sequence-id": _POLICER_SEQ,
                    "peak-rate-kbps": rate_kbps,
                    "committed-rate-kbps": rate_kbps,
                    "maximum-burst-size": burst,
                    "committed-burst-size": burst,
                }],
            }),
        ])
        gc.set(update=[
            (f"/qos/interfaces/interface[interface-id={iface_id}]", {
                "interface-ref": {"interface": iface, "subinterface": subif_idx},
                "input": {"policer-templates": {"policer-template": tpl}},
            }),
        ])


def _gnmi_delete_policer(pe: str, iface: str, subif_idx: int) -> None:
    """Remove the QoS policer-template and its subinterface attachment from *pe*."""
    iface_id = _qos_iface_id(pe, iface, subif_idx)
    tpl = f"{_POLICER_TEMPLATE_PREFIX}-{iface_id}"
    with _gnmi(pe) as gc:
        logger.info("gNMI Delete: policer on %s/%s.%d", pe, iface, subif_idx)
        gc.set(delete=[
            f"/qos/interfaces/interface[interface-id={iface_id}]",
            f"/qos/policer-templates/policer-template[name={tpl}]",
        ])


def _tc_apply(ce: str, rate_mbps: float) -> None:
    """
    Apply a token-bucket rate limiter on *ce*'s eth1 (egress from CE).

    This is the actual enforcement point in the container PoC.  Traffic leaving
    the CE is throttled here, mirroring a policer on the connected PE's ingress.
    tc tbf is chosen for its minimal latency impact at low rates.
    """
    rate_kbps = int(rate_mbps * 1000)
    burst_kbit = max(32, rate_kbps // 8)
    container = _container(ce)
    logger.info("tc: %d kbps tbf on %s/eth1", rate_kbps, container)
    subprocess.run(
        ["docker", "exec", container, "tc", "qdisc", "del", "dev", "eth1", "root"],
        capture_output=True,
    )
    subprocess.run(
        ["docker", "exec", container,
         "tc", "qdisc", "add", "dev", "eth1", "root",
         "tbf", "rate", f"{rate_kbps}kbit",
         "burst", f"{burst_kbit}kbit",
         "latency", "400ms"],
        check=True, capture_output=True,
    )


def _tc_remove(ce: str) -> None:
    """Remove the token-bucket qdisc from *ce*'s eth1."""
    container = _container(ce)
    logger.info("tc: removing qdisc from %s/eth1", container)
    subprocess.run(
        ["docker", "exec", container,
         "tc", "qdisc", "del", "dev", "eth1", "root"],
        capture_output=True,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def wait_for_gnmi(pe: str, timeout: int = 90) -> None:
    """
    Poll until gNMI on *pe* is responsive.

    SR Linux takes 30–60 s to boot after containerlab deploy returns.  Call
    this before the first allocate_bandwidth to avoid connection errors.

    Args:
        pe:      Short PE name, e.g. "pe1".
        timeout: Maximum seconds to wait (default 90).

    Raises:
        TimeoutError if gNMI is not ready within *timeout* seconds.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _gnmi(pe) as gc:
                gc.capabilities()
                logger.info("gNMI ready on %s", pe)
                return
        except Exception:
            logger.debug("gNMI not ready on %s, retrying...", pe)
            time.sleep(3)
    raise TimeoutError(f"gNMI on {pe} not ready after {timeout}s")


def allocate_bandwidth(request: ServiceRequest) -> AllocationResult:
    """
    Allocate *request.mbps* of ingress bandwidth on *request.subinterface* of *request.pe*.

    Pushes a QoS policer-template to the SR Linux PE via gNMI (intent layer),
    then applies a tc rate-limiter on the connected CE container's eth1 for
    actual enforcement (see module docstring for why both are needed).

    Args:
        request: ServiceRequest containing customer_id, pe, subinterface, and mbps.

    Returns:
        AllocationResult describing what succeeded.
    """
    if "." not in request.subinterface:
        raise ValueError(f"subinterface must include subif index: 'ethernet-1/2.0', got {request.subinterface!r}")
    iface, subif_str = request.subinterface.rsplit(".", 1)
    subif_idx = int(subif_str)
    rate_kbps = int(request.mbps * 1000)

    logger.info("allocate_bandwidth(customer=%s, %s, %s, %.1f Mbps)",
                request.customer_id, request.pe, request.subinterface, request.mbps)
    gnmi_ok = tc_ok = False

    try:
        _gnmi_push_policer(request.pe, iface, subif_idx, rate_kbps)
        gnmi_ok = True
        logger.info("gNMI policer config committed on %s", request.pe)
    except Exception as exc:
        logger.warning("gNMI push failed (container datapath note: non-fatal): %s", exc)

    ce = _PE_SUBIF_TO_CE.get((request.pe, request.subinterface))
    if ce:
        try:
            _tc_apply(ce, request.mbps)
            tc_ok = True
            logger.info("tc enforcement applied on %s/eth1", ce)
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.decode() if exc.stderr else str(exc)
            return AllocationResult(False, request.customer_id, request.pe, request.subinterface,
                                    request.mbps, gnmi_ok, False, f"tc failed on {ce}: {err}")
    else:
        logger.warning("No CE mapped for (%s, %s) — tc not applied", request.pe, request.subinterface)

    return AllocationResult(
        success=gnmi_ok or tc_ok,
        customer_id=request.customer_id,
        pe=request.pe,
        subinterface=request.subinterface,
        mbps=request.mbps,
        gnmi_pushed=gnmi_ok,
        tc_applied=tc_ok,
        message=f"gNMI={'ok' if gnmi_ok else 'skip'}, tc={'ok' if tc_ok else 'skip'}",
    )


def revoke_bandwidth(request: ServiceRequest) -> None:
    """
    Remove the bandwidth allocation on *request.subinterface* of *request.pe*.

    Deletes the gNMI policer config and removes the tc rate-limiter from the
    connected CE container.

    Args:
        request: ServiceRequest identifying the allocation to revoke.
    """
    if "." not in request.subinterface:
        raise ValueError(f"subinterface must include index: 'ethernet-1/2.0', got {request.subinterface!r}")
    iface, subif_str = request.subinterface.rsplit(".", 1)
    subif_idx = int(subif_str)

    logger.info("revoke_bandwidth(customer=%s, %s, %s)", request.customer_id, request.pe, request.subinterface)

    try:
        _gnmi_delete_policer(request.pe, iface, subif_idx)
        logger.info("gNMI policer removed from %s", request.pe)
    except Exception as exc:
        logger.warning("gNMI delete failed (non-fatal): %s", exc)

    ce = _PE_SUBIF_TO_CE.get((request.pe, request.subinterface))
    if ce:
        _tc_remove(ce)
        logger.info("tc rate-limit removed from %s/eth1", ce)


def verify_bandwidth(
    src_ce: str,
    dst_ce: str,
    expected_mbps: Optional[float] = None,
    tolerance: float = 0.2,
) -> VerifyResult:
    """
    Measure throughput from *src_ce* to *dst_ce* and optionally verify a target.

    Uses iperf3 UDP at 3× the expected rate (or 20 Mbps for baseline).  The
    sender-reported throughput is used as the measurement: tc shaping on the
    src_ce egress interface limits how fast the sender can push, giving a
    reliable reading even when receiver-side reporting is unreliable (known
    issue in the SR Linux container environment).

    Args:
        src_ce:        Source CE name, e.g. "ce1".
        dst_ce:        Destination CE name, e.g. "ce2".
        expected_mbps: If given, check measured is within tolerance of this.
        tolerance:     Fraction allowed as measurement error (default 0.2 = ±20%).

    Returns:
        VerifyResult.  passed=True if expected_mbps is None (baseline measure).
    """
    dst_ip = _CE_DATA_IP.get(dst_ce)
    if not dst_ip:
        raise ValueError(f"Unknown CE: {dst_ce!r}")

    probe_mbps = max((expected_mbps or 0) * 3, 20.0)
    dst_container = _container(dst_ce)
    src_container = _container(src_ce)

    logger.info("verify_bandwidth: UDP %s→%s probe=%.0f Mbps", src_ce, dst_ce, probe_mbps)

    # Start one-shot iperf3 server on destination
    subprocess.run(
        ["docker", "exec", "-d", dst_container, "iperf3", "-s", "-1", "-p", "5201"],
        check=True,
    )
    time.sleep(1)

    result = subprocess.run(
        ["docker", "exec", src_container,
         "iperf3", "-c", dst_ip, "-p", "5201",
         "-t", "5", "-u", "-b", f"{int(probe_mbps)}M", "-J"],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        msg = f"iperf3 error: {result.stderr.strip()}"
        logger.error(msg)
        return VerifyResult(False, 0.0, expected_mbps, tolerance, msg)

    try:
        data = json.loads(result.stdout)
        # UDP mode uses end.sum; TCP mode uses end.sum_sent — try both
        end = data["end"]
        section = end.get("sum_sent") or end.get("sum") or {}
        bps = section["bits_per_second"]
        measured = round(bps / 1e6, 2)
    except (KeyError, json.JSONDecodeError) as exc:
        msg = f"iperf3 JSON parse error: {exc}"
        logger.error(msg)
        return VerifyResult(False, 0.0, expected_mbps, tolerance, msg)

    if expected_mbps is None:
        msg = f"Baseline: {measured:.2f} Mbps"
        logger.info(msg)
        return VerifyResult(True, measured, None, tolerance, msg)

    lower = expected_mbps * (1 - tolerance)
    upper = expected_mbps * (1 + tolerance)
    passed = lower <= measured <= upper
    msg = (f"{'PASS' if passed else 'FAIL'}: {measured:.2f} Mbps "
           f"(expected {expected_mbps:.1f} ± {tolerance*100:.0f}%)")
    logger.info(msg)
    return VerifyResult(passed, measured, expected_mbps, tolerance, msg)
