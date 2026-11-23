"""Physical fab layout and the directed OHT rail network.

Layout (metres, x along the central aisle, z across it)::

      row B bays (z > 0)   |  |  |  |  |  |  |  |
      interbay lane  <---------------------------- z = +LANE
         shortcuts       ^        v         ^
      interbay lane  ----------------------------> z = -LANE
      row A bays (z < 0)   |  |  |  |  |  |  |  |

* The interbay rail is a one-way loop (two lanes joined at both ends) with
  one-way shortcuts between the lanes, as in real spine layouts.
* Each tool group gets one bay with a one-way intrabay loop: in on one leg,
  out on the other. Tools sit on both sides of the bay; each tool has a load
  port node on the rail. The bay's stocker (lot buffer) is the first node on
  the inbound leg; queued lots are shown there as FOUP towers.

All quantities are assumptions chosen to resemble a 300 mm fab module.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from fabtwin.core.instance import Instance, ToolKind

BAY_PITCH = 8.0
BAY_LEN = 18.0
LANE = 2.0
LEG = 1.6  # half distance between the two legs of a bay loop
TOOL_OFFSET = 3.2

# Bay order along the aisle: litho in the middle, as fabs centre the bottleneck.
KIND_ORDER = [ToolKind.CLEAN, ToolKind.FURNACE, ToolKind.DEP, ToolKind.LITHO,
              ToolKind.METRO, ToolKind.ETCH, ToolKind.IMPLANT, ToolKind.CMP]


@dataclass(frozen=True)
class Bay:
    group: int
    x: float
    z_sign: int  # +1 row B, -1 row A
    stocker: int  # node id


@dataclass(frozen=True)
class ToolSpot:
    machine: int
    x: float
    z: float
    rot: float
    port: int  # node id on the rail


@dataclass
class RailGraph:
    nodes: list[tuple[float, float]] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    out: list[list[tuple[int, int]]] = field(default_factory=list)  # node -> [(edge, to)]

    def add_node(self, x: float, z: float) -> int:
        self.nodes.append((round(x, 3), round(z, 3)))
        self.out.append([])
        return len(self.nodes) - 1

    def add_edge(self, u: int, v: int) -> int:
        if u == v:
            raise ValueError("self loop")
        self.edges.append((u, v))
        e = len(self.edges) - 1
        self.out[u].append((e, v))
        return e

    def length(self, e: int) -> float:
        (x1, z1), (x2, z2) = self.nodes[self.edges[e][0]], self.nodes[self.edges[e][1]]
        return math.hypot(x2 - x1, z2 - z1)

    def dist(self, u: int, v: int) -> float:
        (x1, z1), (x2, z2) = self.nodes[u], self.nodes[v]
        return math.hypot(x2 - x1, z2 - z1)

    def astar(self, src: int, dst: int, edge_cost: list[float] | None = None,
              speed: float = 1.0) -> tuple[list[int], float]:
        """Shortest path (edge list, cost) by A* with a Euclidean heuristic.

        ``edge_cost`` (time units) overrides length / speed; the heuristic stays
        admissible as long as every edge cost >= length / speed.
        """
        if src == dst:
            return [], 0.0
        g = {src: 0.0}
        prev: dict[int, tuple[int, int]] = {}
        pq = [(self.dist(src, dst) / speed, 0.0, src)]
        while pq:
            _, gu, u = heapq.heappop(pq)
            if u == dst:
                path = []
                while u != src:
                    e, u = prev[u]
                    path.append(e)
                return path[::-1], gu
            if gu > g.get(u, math.inf):
                continue
            for e, v in self.out[u]:
                c = edge_cost[e] if edge_cost is not None else self.length(e) / speed
                gv = gu + c
                if gv < g.get(v, math.inf) - 1e-12:
                    g[v] = gv
                    prev[v] = (e, u)
                    heapq.heappush(pq, (gv + self.dist(v, dst) / speed, gv, v))
        raise ValueError(f"no path {src} -> {dst}")


@dataclass
class FabLayout:
    graph: RailGraph
    bays: list[Bay]
    tools: list[ToolSpot]
    width: float
    depth: float

    def to_dict(self, inst: Instance) -> dict[str, object]:
        return {
            "nodes": self.graph.nodes,
            "edges": self.graph.edges,
            "bays": [
                {"group": b.group, "name": inst.groups[b.group].name,
                 "kind": inst.groups[b.group].kind.value, "x": b.x, "side": b.z_sign,
                 "stocker": b.stocker, "len": BAY_LEN, "pitch": BAY_PITCH}
                for b in self.bays
            ],
            "machines": [
                {"id": t.machine, "name": inst.machines[t.machine].name,
                 "group": inst.machines[t.machine].group,
                 "kind": inst.groups[inst.machines[t.machine].group].kind.value,
                 "x": t.x, "z": t.z, "rot": t.rot, "port": t.port,
                 "batch_max": inst.groups[inst.machines[t.machine].group].batch_max}
                for t in self.tools
            ],
            "width": self.width,
            "depth": self.depth,
        }


def build_layout(inst: Instance) -> FabLayout:
    """Deterministic layout for an instance (one bay per tool group)."""
    order = sorted(range(len(inst.groups)),
                   key=lambda g: (KIND_ORDER.index(inst.groups[g].kind), g))
    n = len(order)
    per_row = math.ceil(n / 2)
    # alternate rows so related areas face each other across the aisle
    slots = [(i // 2, -1 if i % 2 == 0 else 1) for i in range(n)]
    x0 = BAY_PITCH
    width = x0 * 2 + per_row * BAY_PITCH
    G = RailGraph()

    # interbay lanes: nodes at each bay's two leg positions plus the ends
    xs = sorted({round(x0 + c * BAY_PITCH + d, 3) for c in range(per_row) for d in (-LEG, LEG)})
    xs = [x0 - BAY_PITCH / 2] + xs + [x0 + per_row * BAY_PITCH - BAY_PITCH / 2]
    lane_a = {x: G.add_node(x, -LANE) for x in xs}  # runs +x
    lane_b = {x: G.add_node(x, +LANE) for x in xs}  # runs -x
    for a, b in zip(xs, xs[1:]):
        G.add_edge(lane_a[a], lane_a[b])
        G.add_edge(lane_b[b], lane_b[a])
    G.add_edge(lane_a[xs[-1]], lane_b[xs[-1]])  # turn-around loops
    G.add_edge(lane_b[xs[0]], lane_a[xs[0]])
    # one-way shortcuts every two bays, alternating direction
    for k, c in enumerate(range(1, per_row, 2)):
        x = round(x0 + c * BAY_PITCH - BAY_PITCH / 2, 3)
        if x not in lane_a:
            na, nb = G.add_node(x, -LANE), G.add_node(x, LANE)
            lane_a[x], lane_b[x] = na, nb
            # splice into lanes
            xs_sorted = sorted(lane_a)
            i = xs_sorted.index(x)
            lo, hi = xs_sorted[i - 1], xs_sorted[i + 1]
            _resplice(G, lane_a[lo], lane_a[hi], na)
            _resplice(G, lane_b[hi], lane_b[lo], nb)
        if k % 2 == 0:
            G.add_edge(lane_a[x], lane_b[x])
        else:
            G.add_edge(lane_b[x], lane_a[x])

    bays: list[Bay] = []
    tools: list[ToolSpot] = []
    for gid, (col, side) in zip(order, slots):
        xc = round(x0 + col * BAY_PITCH, 3)
        # traffic direction on the adjacent lane decides which leg is inbound
        if side < 0:  # lane A runs +x: enter at the left leg
            x_in, x_out, lane = round(xc - LEG, 3), round(xc + LEG, 3), lane_a
        else:  # lane B runs -x: enter at the right leg
            x_in, x_out, lane = round(xc + LEG, 3), round(xc - LEG, 3), lane_b
        machines = inst.groups[gid].machines
        n_ports = max(3, math.ceil(len(machines) / 2) + 1)
        zs = [side * (LANE + 2.0 + (BAY_LEN - 3.0) * k / (n_ports - 1)) for k in range(n_ports)]
        leg_in = [G.add_node(x_in, z) for z in zs]
        leg_out = [G.add_node(x_out, z) for z in reversed(zs)]
        G.add_edge(lane[x_in], leg_in[0])
        for u, v in zip(leg_in, leg_in[1:]):
            G.add_edge(u, v)
        G.add_edge(leg_in[-1], leg_out[0])
        for u, v in zip(leg_out, leg_out[1:]):
            G.add_edge(u, v)
        G.add_edge(leg_out[-1], lane[x_out])
        bays.append(Bay(gid, xc, side, leg_in[0]))
        # tools: alternate outer side of inbound and outbound legs, skip stocker port
        spots = [(leg_in[k], x_in, zs[k]) for k in range(1, n_ports)]
        spots += [(leg_out[k], x_out, zs[n_ports - 1 - k]) for k in range(0, n_ports - 1)]
        spots.sort(key=lambda s: (abs(s[2]), s[1]))
        for mid, (port, xp, zp) in zip(machines, spots):
            outward = 1.0 if xp > xc else -1.0
            tools.append(ToolSpot(mid, round(xp + outward * TOOL_OFFSET, 3), round(zp, 3),
                                  0.0 if outward > 0 else math.pi, port))
    tools.sort(key=lambda t: t.machine)
    depth = 2 * (LANE + BAY_LEN + 2.0)
    return FabLayout(G, sorted(bays, key=lambda b: b.group), tools, width, depth)


def _resplice(G: RailGraph, u: int, w: int, mid: int) -> None:
    """Replace edge u->w by u->mid->w (keeps edge ids of others stable)."""
    for i, (a, b) in enumerate(G.edges):
        if a == u and b == w:
            G.edges[i] = (u, mid)
            G.out[u] = [(e, mid if (e == i) else v) for e, v in G.out[u]]
            G.add_edge(mid, w)
            return
    raise ValueError("edge to splice not found")


def strongly_connected(G: RailGraph) -> bool:
    """True if every node can reach every other node (needed for transport)."""
    def reach(adj: list[list[int]]) -> int:
        seen, stack = {0}, [0]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        return len(seen)

    fwd = [[v for _, v in G.out[u]] for u in range(len(G.nodes))]
    rev: list[list[int]] = [[] for _ in G.nodes]
    for u, v in G.edges:
        rev[v].append(u)
    n = len(G.nodes)
    return reach(fwd) == n and reach(rev) == n
