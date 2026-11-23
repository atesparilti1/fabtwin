## Mathematical formulation

### Sets and data

| Symbol | Meaning |
|---|---|
| $J$ | lots (jobs), each with release $r_j$, due date $d_j$, weight $w_j$ (hot lots: 10) |
| $O_j = (o_{j1},\dots,o_{jn_j})$ | route of lot $j$ (re-entrant: the same tool group appears many times) |
| $G$, $M_g$ | tool groups and their parallel, non-identical machines |
| $M_o \subseteq M_{g(o)}$ | machines qualified for operation $o$ (litho dedication) |
| $p_{om}$ | processing time of $o$ on $m$ ($= p_o / \text{speed}_m$, integer time units of 0.1 h) |
| $\rho_o$ | recipe of $o$ (reticle on litho, process on furnaces, species on implant) |
| $s_g$ | setup time on $g$ when consecutive recipes differ ($s_g = 0$ for most groups) |
| $K_g$ | batch capacity ($K_g = 6$ on furnaces, 1 elsewhere) |
| $Q_o$ | Q-time limit between the end of $o$ and the start of its successor (clean → furnace: 4 h) |
| $\tau$ | transport time between consecutive operations |

### CP-SAT model (`fabtwin/core/cpsat.py`)

Decision variables: start $S_o$, end $E_o$; presence literals $x_{om}\in\{0,1\}$ with optional intervals $I_{om} = [S_o, S_o + p_{om})$.

$$
\begin{aligned}
\min\ & \sum_{j\in J} w_j T_j \\
\text{s.t. } & \textstyle\sum_{m\in M_o} x_{om} = 1 && \forall o \\
& x_{om} \Rightarrow E_o = S_o + p_{om} && \forall o, m \in M_o\\
& S_{o_{j1}} \ge r_j,\quad S_{o_{j,k+1}} \ge E_{o_{jk}} + \tau && \forall j,k\\
& S_{o_{j,k+1}} - E_{o_{jk}} \le Q_{o_{jk}} && \forall j,k: Q \text{ defined}\\
& \textsc{Circuit}\big(\{0\}\cup\{o: m\in M_o\},\ \ell_{ab}\big),\ \ \ell_{ab} \Rightarrow S_b \ge E_a + s_g[\rho_a\ne\rho_b] && \forall m: s_{g(m)}>0\\
& \textsc{NoOverlap}(\{I_{om}\}) && \forall m: s_{g(m)}=0, K_{g(m)}=1\\
& x_{am}\wedge x_{bm} \Rightarrow (E_a\le S_b)\vee(E_b\le S_a)\vee(\beta_{ab}\wedge S_a=S_b),\ \ \beta_{ab}=0 \text{ if } \rho_a\ne\rho_b && \forall m: K_{g(m)}>1\\
& \textsc{Cumulative}(\{I_{om}\}, 1, K_{g(m)}) && \forall m: K_{g(m)}>1\\
& T_j \ge E_{o_{jn_j}} - d_j,\quad T_j \ge 0 && \forall j
\end{aligned}
$$

The circuit constraint uses self-loops for operations not assigned to $m$ and a depot node, so the first operation on a machine needs no setup (as in the simulator). Batch durations are equal for all operations of one recipe on one machine by construction (the batch time is the recipe's time), which makes pairwise synchronisation exact.

### Time-indexed MIP (`fabtwin/core/mip.py`, HiGHS)

$x_{omt}=1$ if $o$ starts on $m$ at period $t$; $z_{m\rho t}=1$ if a batch of recipe $\rho$ starts on batch machine $m$ at $t$.

$$
\begin{aligned}
\min\ & \sum_j w_j T_j\\
& \textstyle\sum_{m,t} x_{omt} = 1, \qquad S_o=\sum_{m,t} t\,x_{omt}, \qquad E_o = \sum_{m,t}(t+p_{om})\,x_{omt}\\
& S_{o_{j,k+1}} \ge E_{o_{jk}}+\tau, \qquad S_{o_{j,k+1}} - E_{o_{jk}} \le Q_{o_{jk}}\\
& u_{m\rho t} := \textstyle\sum_{o:\rho_o=\rho}\ \sum_{t'=t-p_{om}+1}^{t} x_{omt'}, \qquad \sum_\rho u_{m\rho t}\le 1 && (K=1)\\
& u_{m\rho t} + \textstyle\sum_{o:\rho_o\neq\rho}\ \sum_{t'=t+1}^{t+s_g} x_{omt'} \le 1 && \text{(setups)}\\
& x_{omt}\le z_{m\rho_o t},\quad \textstyle\sum_{o:\rho_o=\rho} x_{omt}\le K_g z_{m\rho t},\quad \sum_\rho\sum_{t'=t-P_{m\rho}+1}^{t} z_{m\rho t'}\le 1 && (K>1)\\
& T_j \ge E_{o_{jn_j}} - d_j,\ T_j\ge 0
\end{aligned}
$$

Both models use the same integer grid and solve the same problem; on instances where both prove optimality the objective values coincide (asserted in `tests/test_optim.py`). The MIP horizon is 1.25× the best heuristic makespan, so the MIP optimum is exact on that horizon.

### Stochastic fab (simulation model, `fabtwin/sim/engine.py`)

Lots are released by a renewal process (Gamma inter-arrivals, CV 1) plus Poisson hot lots. Processing times are lognormal around $p_{om}$ (CV 3–15% by area). Machines fail after Weibull calendar times (shape 1.2–2.2) and are repaired after lognormal times; a failure pauses the current job (preempt-resume). Overlay metrology sends 3% of lots back to litho (rework). A lot that misses a Q-time window is re-cleaned; after two re-cleans it is scrapped. Age-based PM renews a machine after $\tau_g$ hours of age (PM waits for the current job). OHT vehicles move on the directed rail graph with headway-based reservations.

### Maintenance: nominal vs robust

The nominal interval minimises long-run down fraction per tool (age-replacement renewal-reward):

$$
D(\tau)=\frac{F(\tau)\,\mathrm{MTTR}+R(\tau)\,T_{PM}}{\int_0^{\tau}R(t)\,dt + F(\tau)\,\mathrm{MTTR}+R(\tau)\,T_{PM}},\qquad F(t)=1-e^{-(t/\lambda)^k}.
$$

It treats every tool hour as equally valuable and ignores repair variability. The robust plan scales these intervals separately for litho and other tools, $\tau_g = m_{\text{litho}}\tau_g^*$ or $m_{\text{other}}\tau_g^*$, and selects the multipliers in the stochastic simulator by two-stage screening and selection with common random numbers (objective: mean cycle time), validated afterwards on fresh seeds.
