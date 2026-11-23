# Replay data format (v1)

Produced by `scripts/export_scenarios.py` (Python simulator, `fabtwin/sim/export.py`).
All times are **hours since simulation start** (float, 1e-4 h resolution). The
replay window is `[meta.t0, meta.t1]` (7 days by default). Every scenario uses the
same instance and random seed, so two scenarios can be shown side by side (compare mode).

## `data/index.json`
```json
{ "seed": 7, "instance": "medium-s0",
  "scenarios": [ { "id": "baseline", "title": "...", "subtitle": "...", "file": "baseline.json", "bytes": 7980000 } ] }
```

## `data/<scenario>.json`

| key | shape | meaning |
|---|---|---|
| `meta` | object | `id,title,subtitle,instance,seed,rule,transport,oht_policy,n_vehicles,pm,t0,t1,kpis_full_run{...}` |
| `layout.nodes` | `[[x,z],...]` | rail nodes, metres. Floor plane is x (along aisle, 0..`layout.width`) and z (across, −depth/2..+depth/2). Rail hangs at ceiling height (suggest y≈4.2 m). |
| `layout.edges` | `[[u,v],...]` | directed rail segments (one-way) between node indices |
| `layout.bays` | `[{group,name,kind,x,side,stocker,len,pitch}]` | one bay per tool group. Bay centre at `x`, extends from the aisle (|z|≈2) to |z|≈2+len on side `side` (−1 → z<0, +1 → z>0). `stocker` = rail node where queued lots wait (draw FOUP towers here). |
| `layout.machines` | `[{id,name,group,kind,x,z,rot,port,batch_max}]` | tool positions (floor, metres), yaw `rot` (rad), rail node of its load port |
| `layout.width`, `layout.depth` | number | floor size |
| `groups` | `[{id,name,kind,batch_max,setup_h,machines}]` | tool groups; `kind` ∈ litho, etch, dep, furnace, implant, cmp, clean, metro |
| `products` | `[{id,name,steps:[[group,recipe,proc_h,has_qtime,layer],...]}]` | routes (re-entrant) |
| `lots` | `[[id,product,hot,release,due,done,scrapped],...]` | every lot that appears in the window. `hot` 0/1; `done`/`scrapped` may be null |
| `mstate` | `[[t,machine,state],...]` sorted by t | machine state changes. First entries (t = t0) are the initial state of every machine. state: 0 idle, 1 setup, 2 processing, 3 down (failure), 4 PM |
| `lotloc` | `[[t,lot,kind,id],...]` sorted by t | lot location changes; entries at t0 are the initial location of every lot in the fab. kind: 0 queue at group `id` (stocker of that bay), 1 on machine `id`, 2 on vehicle `id`, 3 done (leaves fab), 4 scrapped, 5 waiting at rail node `id` for pickup, 6 in fixed-delay transit to group `id` |
| `qtime` | `[[lot,open,deadline,close,violated],...]` | Q-time windows: opened at `open`, must start next step by `deadline`; `close` (null if still open at t1) and `violated` 0/1. A lot is "Q-time critical" while open; pulse red as `t → deadline`. |
| `vehicles` | `vehicles[v] = [[lot, [[t,node],...]], ...]` | OHT vehicle legs. `lot = -1` → empty travel to a pickup, else loaded with that lot (the FOUP rides under the vehicle). Waypoints are node arrivals; interpolate linearly between consecutive waypoints (a repeated node = waiting). Between legs the vehicle is parked at the last node. |
| `ops` | `[[lot,step,machine,setup_start,proc_start,end,recipe,batch],...]` | operations overlapping the window (for Gantt and lot journey). `proc_start`/`end` may be null if unfinished. Same `batch` id = processed together (furnace batch). |
| `events` | `[[t,type,lot,machine],...]` | jump-to-event list: `fail`, `repair`, `pm`, `pm_end`, `qviol`, `scrap`, `hot` (hot-lot release) |
| `series` | `{t:[],wip:[],thr:[],ct:[],ontime:[],litho:[]}` | KPIs every 0.25 h: WIP (lots), rolling-24 h throughput (lots/day), mean cycle time of lots finished in last 24 h (days), on-time % (last 24 h), litho utilisation (busy+setup share, rolling 24 h) |

## `data/analytics.json` (benchmark results, from `make bench`)

Sections may be missing until the corresponding step has been run; the UI must
show a neutral "not yet computed" state, never placeholder numbers.

```jsonc
{
  "dispatch": { "replications": 200, "instance": "...", "kpis": [{"key":"...","label":"...","better":"lower|higher"}],
                "rows": [{"policy":"FIFO", "values": {"<kpi>": {"mean":0,"hw":0}}}] },
  "exact":    { "rows": [{"instance":"s1","lots":6,"cpsat_obj":0,"cpsat_bound":0,"cpsat_status":"OPTIMAL","cpsat_s":0,
                          "mip_obj":0,"mip_bound":0,"mip_s":0,"heuristics":{"FIFO":0,"ATC":0},"alns":0}] },
  "scaling":  { "rows": [{"lots":0,"cpsat_s":0,"alns_s":0,"gap_pct":0}] },
  "pareto":   { "x":"label","y":"label","points": [{"method":"ALNS","x":0,"y":0,"front":true}] },
  "convergence": { "series": [{"name":"ALNS","iter":[],"best":[],"current":[]}] },
  "oht":      { "rows": [{"vehicles":4,"policy":"hungarian","wait_min":{"mean":0,"hw":0},"qviol_pct":{"mean":0,"hw":0}}] },
  "maintenance": { "rows": [{"policy":"run-to-failure","tardiness":{"mean":0,"hw":0},"down_pct":{"mean":0,"hw":0}}] },
  "headline": { "rows": [{"policy":"...","values":{"<kpi>":{"mean":0,"hw":0}}}], "deltas": [{"label":"...","mean":0,"hw":0,"unit":"%"}] }
}
```
