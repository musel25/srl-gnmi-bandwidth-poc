# What are we simulating?

## The real-world scenario

Think of an **internet service provider** (ISP) that sells bandwidth to business customers. The ISP has its own internal network of routers, and each business customer connects to that network through a dedicated port on one of the ISP's edge routers.

```
[Customer A's office] ── [ISP edge router] ── [ISP backbone] ── [ISP edge router] ── [Customer A's datacenter]
```

---

## What each node represents

| Container | Real-world equivalent |
|---|---|
| `ce1`, `ce2`, `ce3`, `ce4` | **Customer premises equipment** — the router or server sitting at a customer's site. They just send and receive traffic; they have no knowledge of the ISP's internal network. |
| `pe1`, `pe2` | **Provider edge routers** — the ISP's routers that face the customers. Each customer plugs a cable into one port of a PE. This is the point where the ISP controls what that customer can do. |
| `p1` | **Provider backbone router** — a core transit router inside the ISP's network. Customers never touch it directly; it just forwards traffic between the two edge routers. |

Full picture:

```
[ce1 = Customer A's office]       ─── pe1 (ISP edge) ─── p1 (ISP core) ─── pe2 (ISP edge) ───  [ce2 = Customer A's datacenter]
[ce3 = Customer B's office]       ───/                                                   \───  [ce4 = Customer B's datacenter]
```

Two different customers, both connected to the same ISP, both sending traffic through the same backbone.

---

## What "allocating bandwidth" means

When Customer A signs a contract for "5 Mbps guaranteed", the ISP needs to enforce that on their network. The enforcement point is the **PE router's ingress port** — the moment Customer A's traffic enters the ISP's network.

`allocate_bandwidth` does exactly that:

1. **Tells the PE router** — "on the port where Customer A is connected, apply a policer that caps ingress traffic at 5 Mbps". This is the gNMI write to SR Linux. It's the authoritative intent record on the router.
2. **Enforces it** — since the containerized SR Linux image can't enforce policers in software (hardware-only feature), `tc tbf` on the CE's outgoing interface acts as the enforcement point instead.

It is not "priority" — it is a **hard rate cap**. Customer A physically cannot send more than 5 Mbps into the network, regardless of how fast their internal link is.

---

## The paper connection

This PoC models the activation step from the paper:

1. A **consumer AI agent** negotiates a bandwidth contract with a **provider AI agent**
2. Payment is locked in a smart-contract escrow on-chain
3. The provider agent mints an NFT credential and hands it to the consumer
4. The consumer agent calls `allocate_bandwidth` as an MCP tool to activate the service

The network literally turns on the pipe at the agreed rate. This repo isolates step 4 only — agents, escrow, and NFTs are out of scope here.

---

## The two customers sharing a PE

This is the interesting part of Phase 2. Both `ce1` and `ce3` connect to `pe1` — different ports, but the same physical router. The demo runs both allocations simultaneously:

```
orange-labs: 5 Mbps cap on pe1 / ethernet-1/2.0  (ce1 side)
inria-net:   3 Mbps cap on pe1 / ethernet-1/3.0  (ce3 side)
```

Two independent contracts, two independent policers, both active on the same router at the same time. The key thing being tested: revoking one customer's allocation must not affect the other's. That is exactly the bug that was discovered and fixed in Phase 2 — SR Linux refuses to delete a policer-template that is still referenced by another subinterface on the same PE. The fix was to give each subinterface its own uniquely-named template (`clab-bw-pe1-e1-2-0`, `clab-bw-pe1-e1-3-0`) so the two allocations are fully independent.
