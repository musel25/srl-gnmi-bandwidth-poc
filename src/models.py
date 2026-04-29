from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ServiceRequest:
    """Bandwidth service request submitted by a customer agent."""
    customer_id: str
    pe: str           # e.g. "pe1"
    subinterface: str # e.g. "ethernet-1/2.0"
    mbps: float       # target rate in Mbps
