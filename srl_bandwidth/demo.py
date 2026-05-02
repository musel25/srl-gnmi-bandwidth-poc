"""
Phase 2 demo: ServiceRequest API — two customers allocated and verified simultaneously.

Run with:  uv run python -m srl_bandwidth.demo
"""

import logging
import sys
import time

from srl_bandwidth.bandwidth import (
    AllocationResult,
    VerifyResult,
    allocate_bandwidth,
    revoke_bandwidth,
    verify_bandwidth,
    wait_for_gnmi,
)
from srl_bandwidth.models import ServiceRequest

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

CUSTOMER_A = ServiceRequest(
    customer_id="orange-labs",
    pe="pe1",
    subinterface="ethernet-1/2.0",
    mbps=5.0,
)
CUSTOMER_B = ServiceRequest(
    customer_id="inria-net",
    pe="pe1",
    subinterface="ethernet-1/3.0",
    mbps=3.0,
)
TOLERANCE = 0.4


def hr(char: str = "─", width: int = 60) -> str:
    return char * width


def section(n: int, title: str) -> None:
    print(f"\n{hr('═')}")
    print(f"  Step {n}: {title}")
    print(hr("─"))


def print_result(label: str, value: object) -> None:
    print(f"  {label:<22} {value}")


def main() -> int:
    print(hr("═"))
    print("  ContainerLab Bandwidth Allocation PoC — Phase 2 Demo")
    print("  ServiceRequest API — two customers, two allocations")
    print(hr("═"))

    section(0, "Waiting for SR Linux gNMI to be ready")
    for pe in ("pe1", "pe2"):
        try:
            wait_for_gnmi(pe, timeout=90)
            print(f"  {pe} gNMI: ready")
        except TimeoutError as exc:
            print(f"  ERROR: {exc}")
            return 1

    section(1, "Baseline measurement (no rate limits)")
    base_ab: VerifyResult = verify_bandwidth("ce1", "ce2")
    base_cd: VerifyResult = verify_bandwidth("ce3", "ce4")
    print_result("ce1→ce2 baseline:", f"{base_ab.measured_mbps:.2f} Mbps")
    print_result("ce3→ce4 baseline:", f"{base_cd.measured_mbps:.2f} Mbps")

    section(2, "Allocate bandwidth for both customers")
    res_a: AllocationResult = allocate_bandwidth(CUSTOMER_A)
    res_b: AllocationResult = allocate_bandwidth(CUSTOMER_B)
    for req, res in [(CUSTOMER_A, res_a), (CUSTOMER_B, res_b)]:
        print(f"\n  customer={req.customer_id}  pe={req.pe}  {req.mbps} Mbps")
        print_result("  gNMI pushed:", "✓" if res.gnmi_pushed else "✗")
        print_result("  tc applied:", "✓" if res.tc_applied else "✗")
        print_result("  status:", res.message)
        if not res.success:
            print(f"  ERROR: {res.message}")
            return 1

    print("\n  Waiting 2 s for policy to propagate...")
    time.sleep(2)

    section(3, "Verify caps are in effect")
    cap_a: VerifyResult = verify_bandwidth("ce1", "ce2", CUSTOMER_A.mbps, TOLERANCE)
    cap_b: VerifyResult = verify_bandwidth("ce3", "ce4", CUSTOMER_B.mbps, TOLERANCE)
    print_result("ce1→ce2 measured:", f"{cap_a.measured_mbps:.2f} Mbps  (target {CUSTOMER_A.mbps})")
    print_result("ce1→ce2 result:", cap_a.message)
    print_result("ce3→ce4 measured:", f"{cap_b.measured_mbps:.2f} Mbps  (target {CUSTOMER_B.mbps})")
    print_result("ce3→ce4 result:", cap_b.message)

    section(4, "Revoke all allocations")
    revoke_bandwidth(CUSTOMER_A)
    revoke_bandwidth(CUSTOMER_B)
    print("  Both allocations revoked.")

    print("\n  Waiting 2 s for removal to take effect...")
    time.sleep(2)

    section(5, "Verify throughput restored")
    rest_ab: VerifyResult = verify_bandwidth("ce1", "ce2")
    rest_cd: VerifyResult = verify_bandwidth("ce3", "ce4")
    print_result("ce1→ce2 restored:", f"{rest_ab.measured_mbps:.2f} Mbps")
    print_result("ce3→ce4 restored:", f"{rest_cd.measured_mbps:.2f} Mbps")

    rec_ab = rest_ab.measured_mbps >= base_ab.measured_mbps * 0.7
    rec_cd = rest_cd.measured_mbps >= base_cd.measured_mbps * 0.7

    print(f"\n{hr('═')}")
    print("  SUMMARY")
    print(hr("─"))
    print_result("orange-labs cap:", "✓ PASS" if cap_a.passed else "✗ FAIL")
    print_result("inria-net cap:", "✓ PASS" if cap_b.passed else "✗ FAIL")
    print_result("ce1→ce2 restored:", "✓" if rec_ab else "✗")
    print_result("ce3→ce4 restored:", "✓" if rec_cd else "✗")
    print(hr("═"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
