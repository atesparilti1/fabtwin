Coupled fab (4 OHT vehicles, failures, rework, hot lots), 200 CRN replications, mean ± 95% CI.

| Policy | Weighted tardiness (h/lot) | Cycle time (days) | On-time (%) | Throughput (lots/day) | Q-time violations (%) | Hot-lot cycle time (h) | Unplanned down (frac) | Wait for vehicle (min) |
|---|---|---|---|---|---|---|---|---|
| FIFO baseline | 4.627 ± 1.105 | 4.254 ± 0.084 | 79.853 ± 2.716 | 20.538 ± 0.068 | 0.920 ± 0.019 | 67.285 ± 0.130 | 0.026 ± 0.000 | 1.056 ± 0.003 |
| CR baseline | 2.136 ± 0.584 | 4.294 ± 0.062 | 84.862 ± 2.651 | 20.518 ± 0.062 | 1.848 ± 0.033 | 67.437 ± 0.130 | 0.026 ± 0.000 | 1.054 ± 0.003 |
| ATCS + Hungarian | 0.185 ± 0.077 | 3.712 ± 0.027 | 98.103 ± 0.616 | 20.579 ± 0.069 | 1.887 ± 0.030 | 67.367 ± 0.141 | 0.026 ± 0.000 | 1.015 ± 0.003 |
| FabTwin | 0.062 ± 0.051 | 3.602 ± 0.023 | 99.259 ± 0.393 | 20.595 ± 0.070 | 1.875 ± 0.028 | 66.784 ± 0.123 | 0.018 ± 0.000 | 1.014 ± 0.003 |

FabTwin, paired change:

- Weighted tardiness (h/lot): FabTwin vs CR baseline: -97.1% ± 26.2%
- Cycle time (days): FabTwin vs CR baseline: -16.1% ± 1.0%
- On-time (%): FabTwin vs CR baseline: +17.0% ± 3.0%
- Throughput (lots/day): FabTwin vs CR baseline: +0.4% ± 0.1%
- Q-time violations (%): FabTwin vs CR baseline: +1.5% ± 1.9%
- Unplanned down (frac): FabTwin vs CR baseline: -32.0% ± 0.8%
- Weighted tardiness (h/lot): FabTwin vs FIFO baseline: -98.7% ± 23.3%
- Cycle time (days): FabTwin vs FIFO baseline: -15.3% ± 1.6%
- On-time (%): FabTwin vs FIFO baseline: +24.3% ± 3.2%
- Throughput (lots/day): FabTwin vs FIFO baseline: +0.3% ± 0.2%
- Q-time violations (%): FabTwin vs FIFO baseline: +103.8% ± 3.2%
- Unplanned down (frac): FabTwin vs FIFO baseline: -32.0% ± 0.8%

Rolling-horizon CP-SAT litho planning on top of FabTwin (20 reps, paired vs FabTwin):

- mean_weighted_tardiness_h: -11.7% ± 32.2%
- mean_ct_days: +2.6% ± 0.5%
- on_time_pct: -0.0% ± 0.3%
