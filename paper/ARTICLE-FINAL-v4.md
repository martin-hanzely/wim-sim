# The Noise Floor and the Memory Length: Making Adaptive-versus-Static Drift Comparisons Interpretable

**Martin Hanzely¹, Roman Budjač¹**

¹ Institute of Applied Informatics, Automation and Mechatronics, Faculty of Materials Science and Technology in Trnava, Slovak University of Technology in Bratislava, Slovakia

---

## Abstract

Whether a deployed regression model should be refitted online or left frozen is normally settled empirically, by comparing an adaptive learner against a static one on a stream containing drift. We show that such comparisons can return **opposite conclusions on the same scenario**, decided by the estimator's memory length.

Using a sensing pipeline in which a physical noise floor is recorded per sample rather than estimated, we evaluate frozen least squares, recursive least squares across five forgetting factors, periodic batch refitting and a Kalman observer, over seven drift scenarios, two measurement front ends, four out-of-distribution scenarios and 3,765 simulation runs.

On a slow-drift scenario offering 2.7 kg (0.04% of mean vehicle mass) of recoverable error above a 136.1 kg (2.2%) floor, adaptation with a short memory is **worse than freezing by 4.13 kg (0.07%)**, while the same estimator with a long memory recovers about half the available error (1.47 kg, 0.02%; p_holm < 0.001). The reversal is under 0.1% of vehicle mass: the claim is methodological — the sign of the comparison flips with the memory length — not a claim of practical weighing benefit. On an abrupt-drift scenario the ordering reverses, a short memory winning by 7.2 kg (0.12%) on 29 of 30 seeds. A third scenario is best served by an intermediate setting. Each scenario has a different optimal memory length, ordered by the character of its drift, consistent with the classical trade-off between tracking lag and misadjustment. Specifying the observation noise correctly also helps, but by 0.25–3 kg (0.004–0.05%) against the 10–25 kg (0.16–0.41%) attributable to memory length.

A memory length tuned on one scenario transfers to one of two out-of-distribution counterparts (57.8 kg, 0.93%, over frozen, 10 of 10 seeds). On the slow-drift scenario adaptation reduces median absolute bias from 23.67 kg (0.38%) to 5.74 kg (0.09%) not by tracking drift but by discarding the error of the fitting window, which is both small and thermally displaced from deployment conditions.

**Keywords:** concept drift, online learning, misadjustment, forgetting factor, recursive least squares, benchmark methodology.

---

## I. Introduction

### A. A comparison that does not mean what it appears to

The standard empirical argument for online adaptation runs: construct a stream containing drift, fit a static model and an adaptive one, report that the adaptive model wins, conclude that adaptation helps under drift.

That argument has a gap. An adaptive estimator does not only track change; it also responds to noise in the label stream, so its parameters execute a random walk even where the target relationship is static. In adaptive filtering this excess error is **misadjustment**, governed by memory length and trading against tracking lag [CITE-WIDROW], [CITE-HAYKIN], [CITE-LJUNG].

The consequence for benchmark practice is direct. Such a comparison measures the **recoverable error minus the misadjustment incurred recovering it**. Interpreting its result therefore requires both terms: the stream's irreducible error, which bounds what any estimator could recover, and the memory length, which sets what the estimator spends recovering it.

### B. What we show

On one scenario, adaptation with a short memory is measurably worse than doing nothing, while the same estimator with a long memory recovers half the available error. Across three scenarios the optimal memory length differs, and it differs in the order the lag–noise trade-off predicts.

The study is possible because the pipeline records a physical noise floor per sample. The task is estimating vehicle mass from a strain-gauge signal, where suspension oscillation contributes an error component independent of model quality.

### C. Contributions

1. **Simulator and data released for reproduction** (§IV-A, §VI-D): the drift simulator, with a per-sample recorded dynamic-load floor, its configurations, and the per-run values behind every figure and table.
2. **Evidence that adaptive-versus-static comparisons are uninterpretable without both the floor and the memory length**, demonstrated by three scenarios with three different optimal memory lengths and one whose verdict reverses in sign (§V-B, §VI-A).
3. **A quantified ordering of two configuration choices**: memory length dominates observation-noise specification by roughly an order of magnitude (§V-C).
4. **A measured case of fitting-window bias persisting through deployment**: the frozen fit's bias is reconstructed per seed from the fitting window's sampling error and its thermal displacement, and adaptation removes both (§V-E).

---

## II. Background

**Concept drift and online learning.** Drift is categorised by rate and form and handled by continuous adaptation or detect-then-retrain [CITE-GAMA], [CITE-LU]. Detection uses sequential tests on residuals [CITE-PAGE], [CITE-HINKLEY] or adaptive windowing [CITE-BIFET].

**Tracking and misadjustment.** The trade-off we invoke is classical. An adaptive filter's steady-state excess mean-square error decomposes into a lag component falling with faster adaptation and a gradient-noise component rising with it; Widrow's misadjustment quantifies the second [CITE-WIDROW], with standard treatments in [CITE-HAYKIN] and forgetting-factor analysis in [CITE-LJUNG].

**We claim no new principle.** The contribution is to bring this trade-off into drift-benchmark practice with a measured floor, and to show that neglecting it suffices to reverse a published-style conclusion.

**Noise floors in drift benchmarks.** It is not the case that no benchmark offers a known irreducible error: SEA with class noise, the rotating hyperplane and Friedman with additive noise have it by construction. Our distinction is narrower — a **physically structured, per-sample recorded floor in a realistic sensing pipeline**, varying per observation by a physical mechanism rather than injected as a constant. We have not surveyed how often drift studies report a floor or a memory length, and make no claim about prevailing practice.

**The application domain.** Weigh-in-motion calibration uses regression against vehicles of known mass, revised at service intervals [CITE-OIML]. Online recursive updating has been applied in this domain [CITE-BURNOS].

---

## III. Problem setup

### A. The data-generating process

> **(1)** x(t) = q(t) + k(t) · Σⱼ Lⱼ · φ(t − τⱼ) + n(t)

with q(t) a drifting offset, k(t) a drifting gain depending on temperature through a first-order lag, Lⱼ the load of axle j, φ a response shape, n(t) noise. Both q(t) and k(t) constitute concept drift: the mapping from signal to target changes while the input distribution does not. Each crossing yields a scalar feature *s*, the sum of the axle peak amplitudes after offset removal.

### B. The noise floor, relative to the feature

The target is static mass; the sensor observes the instantaneous load of an oscillating vehicle. The difference is independent of the model's parameters and is recorded per crossing.

This **floor** is irreducible **relative to the scalar feature s**. A richer representation — multiple sensors, or the full waveform — could reduce it. We claim no Bayes error for the task. The floor counts dynamic load only: sensor noise n(t) propagated through the feature is not in it (§VI-C). Every excess reported below is therefore an **upper bound** on what an estimator could recover, which makes the recovered percentages of §V-D conservative.

Because mean absolute error is not additive, the **recoverable excess** is a difference, not a component:

> **(2)** excess = MAE_total − MAE_floor

### C. The estimators

The arms differ in the direction of the fitted line. The Kalman observer models the **feature as a function of the mass**,

> **(3)** s = θ₀ + θ₁ · y

and inverts at prediction time, ŷ = (s − θ₀)/θ₁. The frozen fit and recursive least squares regress **mass on the feature**, y = β₀ + β₁ · s, and predict directly. These are the classical and inverse estimators of statistical calibration, which have different bias properties: the inverse estimator is pulled toward the mean of its calibration sample, in exchange for lower error within that sample's range, while the classical estimator does not have this shrinkage but has higher variance [CITE-KRUTCHKOFF], [CITE-OSBORNE]. Both are reported in the sensor direction (θ₀, θ₁) wherever the arms' parameters are compared.

**Frozen** — fitted once by ordinary least squares on the first 60 crossings, and held. **Recursive least squares** with λ ∈ {0.95, 0.99, 0.995, 0.999, 1.0}; λ = 1.0 is a growing-window refit. **Periodic batch refit** at a fixed interval. **Kalman observer** with process noise Q and observation noise R; the gain depends on Q/R.

**TABLE I — Parameters, resolved at the principal sweep's commit and hash-verified**

| Parameter | Symbol | Value | Unit |
|---|---|---|---|
| Forgetting factor (shipped) | λ | 0.99 | — |
| Process noise, offset | Q₀₀ | 1.0 × 10⁻⁷ | feature σ s⁻¹ |
| Process noise, gain | Q₁₁ | 1.0 × 10⁻¹¹ | feature σ kg⁻¹ s⁻¹ |
| Observation noise (shipped) | R | 1.0 × 10⁻⁸ | feature² |
| Observation noise (corrected) | R | 2.933 × 10⁻³ | feature² |
| Initial covariance | P₀ | diag(1.0², 0.01²) | — |
| Maximum propagation gap | max_gap | 3600 | s |
| Thermal coefficient | α | −2.0 × 10⁻⁴ | °C⁻¹ |
| Thermal lag | τ_th | 1800 | s |

Q₀₀ and Q₁₁ are standard deviations, squared internally. The shipped R corresponds to ≈ 0.5 kg of assumed label noise against a ≈ 136 kg floor; the corrected R is the floor variance expressed in feature units.

---

## IV. Experimental design

### A. Why simulation

The claim requires the floor to be known rather than estimated. Tracking claims need the true parameter trajectory; recovery claims need shifts of known magnitude at known times; estimator comparisons need identical repeated conditions.

The simulator records a ground-truth trajectory the estimation path cannot read, enforced by a static import-graph test. Its noise spectrum, drift rate and response shape are fitted from eight recordings of a physical instrument (23 usable crossings). **No vehicle in those recordings was weighed.**

### B. Scenarios

**TABLE II — Scenarios and the frozen model's position (median, 30 seeds, kg)**

| ID | Drift form | Floor | Frozen MAE | Excess | Excess share |
|---|---|---:|---:|---:|---:|
| S1 | none | 0.0 | 0.9 | 0.9 | **100%** |
| S2 | gradual, thermal (72 h) | 136.1 | 138.8 | 2.7 | 2.0% |
| S3 | incremental, random walk | 135.7 | 139.2 | 3.5 | 2.5% |
| S4 | abrupt, two shifts | 136.4 | 182.4 | 46.0 | 25.2% |
| S5 | gradual + label outage | 136.2 | 138.9 | 2.7 | 1.9% |
| S6 | superposed | 191.2 | 696.9 | 505.7 | 72.6% |
| S7 | gradual ramp, sparse labels | 158.3 | 179.0 | 20.7 | 11.6% |

**H1–H4** are generated after all tuning, with different parameter draws, evaluated without adjustment. Fleet mean masses, used for every relative figure in this paper, are 6,075–6,283 kg across scenarios (S2: 6,283 kg).

### C. Protocol

Wilcoxon signed-rank on runs paired by seed, Holm correction within family. The reported statistic is the **median of per-seed paired differences**, arm minus frozen, so a negative value favours the adaptive arm.

**Effect size.** With dᵢ the paired difference on seed i, zeros excluded, n₊ and n₋ the numbers of positive and negative dᵢ, and W₊ and W₋ the sums of the ranks of |dᵢ| over positive and negative dᵢ:

> **(4)** r_sign = (n₊ − n₋) / (n₊ + n₋)  **(5)** r_rank = (W₊ − W₋) / (W₊ + W₋)

We report the **sign-count** form (4) with bootstrap 95% intervals; the rank-weighted form (5), the one the Wilcoxon statistic carries, is in the released data. They coincide when every seed has the same sign (±1.00) and differ when the per-seed magnitudes are skewed: on S6 with the Kalman observer, r_sign = +0.33 and r_rank = +0.46.

Seed counts follow a protocol committed to version control **before any reported run**: ten seeds, escalating to thirty where per-seed signs are not unanimous, **both stages reported**. Cells escalated beyond that requirement, for figure uniformity, are labelled as such. Three results that appeared at ten seeds did not survive escalation and are reported (§V-C, §V-D, §V-G).

**Families.** A single-setting comparison across seven scenarios and two estimators forms a family of fourteen (Table IV); the memory sweep across five settings and three scenarios forms a family of fifteen (Table III). Each corrected p-value names its family.

---

## V. Results

### A. The floor dominates

**FIGURE 1** — *Pipeline and the two error sources.*
**FIGURE 2** — `F2__error_decomposition.png`. Two panels, lower on a log axis.

On four of seven scenarios the frozen model sits within 3.5 kg of a floor above 135 kg; on S2, **98.0% of total error is at the floor**, and the thermal drift the scenario exists to study contributes **0.13 kg** of the remainder (ΔMAE; derivation in the released data).

S1 is reported rather than suppressed: its floor is zero, so its excess share is **100%** — the largest possible — and the best arm recovers **−0.1%**. Share alone cannot be the criterion. Because the floor excludes propagated sensor noise, S1's 0.9 kg is an upper bound on what any arm could recover there.

### B. Three scenarios, three optimal memory lengths

**FIGURE 3** — `F3__forgetting_factor_sweep.png`. **Primary figure.**

**TABLE III — RLS minus frozen, median paired difference, kg (% of fleet mean mass), 30 seeds**

| Scenario | Excess | λ = 0.95 | 0.99 | 0.995 | 0.999 | 1.0 |
|---|---:|---:|---:|---:|---:|---:|
| S2 gradual | 2.7 (0.04%) | **+4.13 (+0.066%)** | −0.80 (−0.013%) | −1.22 (−0.019%) | −1.47 (−0.023%) | **−1.48 (−0.024%)** |
| S4 abrupt | 46.0 (0.74%) | **−35.5 (−0.57%)** | −27.1 (−0.44%) | −23.3 (−0.38%) | −20.6 (−0.33%) | −19.9 (−0.32%) |
| S7 ramp, sparse | 20.7 (0.33%) | −11.8 (−0.19%) | **−14.1 (−0.23%)** | −12.0 (−0.19%) | −6.5 (−0.10%) | −4.7 (−0.08%) |

Fleet mean masses: S2 6,283 kg, S4 6,192 kg, S7 6,202 kg.

Each scenario is best served by a different memory length, and the ordering follows the character of its drift. **Abrupt drift wants the shortest memory** — on S4, λ = 0.95 beats λ = 0.99 by 7.2 kg (0.12%) on 29 of 30 seeds. **Slow drift wants the longest** — on S2 the best setting is the growing window. **A gradual ramp with sparse labels has an interior optimum** at λ = 0.99, degrading in both directions.

**The sign reverses on S2.** With a short memory, adaptation is **worse than doing nothing by 4.13 kg** (25 of 30 seeds, p_holm < 0.001) on a scenario offering only 2.7 kg to recover — more than the entire available excess, which we attribute to misadjustment. With a long memory it recovers about half (−1.47 kg at λ = 0.999, 24 of 30, p_holm < 0.001). The whole reversal is under 0.1% of the S2 fleet mean of 6,283 kg. It matters because the sign of the comparison flips, not because either magnitude matters for weighing.

At the shipped λ = 0.99 the difference is −0.80 kg, better on 19 of 30 seeds, raw p = 0.029, and p_holm = 0.029 within the fifteen-cell family of Table III: a marginal result.

At λ = 0.99 no single-setting comparison on S1, S2, S3 or S5 survives correction in the fourteen-test family of Table IV; Table III shows that on S2 this is a property of the setting, not of the scenario.

The corrected-R Kalman observer has no forgetting factor and no fixed effective memory, so it has no defined position on Figure 3. Its paired differences against frozen are S2 **−1.44 kg** (−0.023%; 30 seeds, 26 of 30, p_holm < 0.001), S4 −18.2 kg (−0.29%; 10 seeds) and S7 −5.29 kg (−0.085%; 30 seeds).

### C. Memory length dominates observation-noise specification

Correcting the observation noise from the shipped value to the floor variance **helps**: the corrected filter at the shipped adaptation rate beats the shipped filter on **8 of 11 scenarios**, by **0.25–3 kg**, with S2, S5 and S7 agreeing on 26–28 of 30 seeds.

Changing the adaptation rate is worth **10–25 kg** on the same scenarios — roughly **ten times more**.

Because the Kalman gain depends on Q/R, rescaling Q to preserve that ratio approximately reproduces the shipped behaviour. The reproduction is approximate rather than exact over a finite run with a finite initial covariance: at thirty seeds the rescaled filter differs by **up to 4.3 kg** (H3 −4.3, H4 −3.0, S5 −2.1), all in its favour. That is small against the 10–25 kg attributable to the adaptation rate, and the ordering stands. At thirty seeds the misspecification of R is small, not negligible.

### D. Effects at a fixed memory length

**FIGURE 4** — `ladder30__accuracy.png`. **FIGURE 5** — `F5__effect_sizes.png`, shipped memory only.

**TABLE IV — Comparisons surviving Holm correction at λ = 0.99 (30 seeds, 14-test family)**

| Scenario | Estimator | Paired difference | Recovered | Effect | p (Holm) |
|---|---|---:|---:|---:|---:|
| S4 | Kalman | −31.6 | 68.7% | −1.00 | 2.6e−08 |
| S4 | RLS | −27.1 | 58.9% | −1.00 | 2.6e−08 |
| S6 | RLS | −32.7 | 6.5% | −1.00 | 2.6e−08 |
| S7 | Kalman | −14.2 | 68.4% | −0.97 | 3.5e−07 |
| S7 | RLS | −14.1 | 68.0% | −1.00 | 2.6e−08 |

Recovered percentages use the excess of Table II and are conservative, since that excess is an upper bound (§III-B). These are valid statements about this configuration; §V-B is why they cannot be read as statements about adaptation in general.

**Periodic batch refitting is worse than recursive least squares at λ = 0.99 on all seven scenarios.** A ten-seed result that it was worse than frozen on S2 did not survive escalation.

**No adverse effect of adaptation survives escalation.** An apparent penalty for the Kalman observer on S6 measured +10.9 kg at thirty seeds with p_holm = 0.24, and the corresponding ladder figure (+12.05 kg) never separated. Its sign-count effect size is +0.33 (20 of 30 seeds unfavourable) with a 95% interval of [0.00, 0.67], touching zero; the rank-weighted form is +0.46. Nothing here depends on it.

One interval does exclude zero on the unfavourable side: the Kalman observer on S1, at **+0.007 kg**. The separation is statistical only; at that magnitude it has no practical consequence.

### E. Adaptation corrects an unrepresentative fitting window

**FIGURE 6** — `s2__gain_tracking.png`. **FIGURE 7** — `F7__bias_by_scenario.png`. **FIGURE 8** — `F8__fitting_window.png`.

On S2 **median absolute bias** falls from **23.67 kg** (0.38%; frozen) to **5.74 kg** (0.09%; RLS) and **5.62 kg** (Kalman), at p_holm = 7.7 × 10⁻⁷ and 2.0 × 10⁻⁶. The corresponding means are 25.76, 5.95 and 5.97 kg. The frozen arm's signed bias has median −17.6 kg and mean −12.0 kg across 30 seeds, with a seed-to-seed standard deviation of 28.8 kg; the adaptive arms' is 6.9 kg (RLS) and 7.2 kg (Kalman). All these statistics are distinct and each is labelled where used.

The mechanism is not drift tracking. Refitting the frozen model on each seed's first 60 crossings from the stored truth reproduces its per-seed signed bias (r = 0.996, median absolute discrepancy 0.66 kg, 10 seeds), and splits it into two terms:

- **A thermal term, −8.4 to −9.6 kg on every seed.** The fitting window spans **20.0 minutes** and sits **7.05 °C below the median temperature of the deployment period** (seed 1). Because α is negative, the gain during the window is 0.146% higher than over deployment, and the inverted model under-predicts: −9.2 kg at the S2 fleet mean of 6,283 kg.
- **A sampling term, −34.5 to +7.8 kg depending on the seed.** This is the error of a least-squares line fitted to 60 crossings whose dynamic load is of the order of the 136 kg floor. It carries the seed-to-seed spread, and with it most of the median absolute bias.

Adaptation removes both. The fall in median absolute bias is therefore mostly the discarding of a small sample's fitting error; the thermal displacement accounts for about 9 kg of it.

Temperature is not a model input, so the thermal term is **not covariate shift**: it is a shift in P(y | s) driven by a hidden variable, produced by an unrepresentative fitting sample. Neither term decays under a frozen fit, and a detection scheme defined as departure from the initial fit is poorly placed to observe them, since the initial fit is itself displaced. We have not tested whether such a scheme would fire.

**One result is partly explained and partly not.** Both adaptive arms sit **two to seven times further** from the true gain trajectory than a constant does, and are anti-correlated with it.

The posterior correlation between θ₀ and θ₁ on S2 is **−0.52** for both RLS and the corrected-R Kalman, matching the geometric prediction −E[m]/√E[m²] for an uncentred regressor. The parameters therefore trade against each other by construction, which permits the pair to move away from truth while the prediction improves. The shipped Kalman sits at −0.29; the corrected observation model puts the posterior where the geometry predicts, a further reason to specify R.

The magnitude is not explained. The ablation most likely to account for it — the thermal scenario with the offset-coupling term disabled — came out **null**, because the zero tracker removes the offset upstream of the estimator. The two-to-sevenfold distance remains unexplained.

### F. Robustness to the measurement front end

**FIGURE 9** — `cintron_ladder30__accuracy.png`. **FIGURE 10** — `F10__instrument_transfer.png`.

**TABLE V — Transfer across front ends (paired differences, kg; 30 seeds)**

| Scenario / estimator | Front end A | Front end B |
|---|---:|---:|
| S4 / Kalman | −31.6 | −33.2 |
| S4 / RLS | −27.1 | −31.8 |
| S6 / RLS | −32.7 | −30.7 |
| S7 / Kalman | −14.2 | −18.1 |
| S7 / RLS | −14.1 | −18.2 |

All five reproduce at effect size −1.00, across a factor of fourteen in sensitivity and a different response physics. Both configurations share the drift and floor models, so this is robustness to the observation model, not independent validation.

### G. A tuned memory transfers to one of two out-of-distribution scenarios

**FIGURE 11** — `heldout30__accuracy.png`. **FIGURE 12** — `F12__development_vs_heldout.png`, with a separate panel for the tuned-memory transfer.

The memory length was **fixed before evaluation** in each case.

- **λ = 0.95, chosen on S4, applied to H2**: beats frozen by **57.8 kg** (0.93% of the H2 fleet mean of 6,225 kg) and λ = 0.99 by **15.0 kg** (0.24%), 10 of 10 seeds each. The transfer holds.
- **λ = 0.999, chosen on S2, applied to H1**: appeared to beat λ = 0.99 at ten seeds but **does not separate at thirty**, and does not beat frozen. **Nothing beats frozen on H1.**

One of two transfers holds. At the shipped memory, three of five in-distribution effects reproduce out of distribution; the two that do not were drawn substantially harder (H1 by 5.6×, H3 by 2.4×), confounding failure with difficulty.

### H. One result we cannot explain

**FIGURE 14** — `F14__h1_process_noise.png`.

On H1 the Kalman observer is worse than frozen by **+251.4 kg** as shipped (4.0% of the H1 fleet mean of 6,276 kg; 30 seeds, 30 of 30) and **+264.4 kg** with corrected observation noise (10 seeds, 10 of 10). The penalty is a spread cost, not a bias cost.

What has been ruled out:

- **Observation noise.** Corrected against shipped R, the difference is +4.8 kg (30 seeds, corrected worse on 16 of 30, p_holm = 1.0); with Q rescaled to the shipped Q/R ratio, −0.7 kg (p_holm = 0.68).
- **Adaptation rate.** The penalty is unchanged at both adaptation rates tested.
- **Process noise.** A sweep across four decades does not account for its magnitude, and the dependence runs opposite to the obvious hypothesis.
- **Instability of the inversion.** Because the observer predicts ŷ = (s − θ̂₀)/θ̂₁, a θ̂₁ drifting toward zero would inflate errors without bound. Per-event diagnostics on ten seeds per arm exclude this: θ̂₁ never changes sign; against the frozen fit's gain on the same vehicle its minimum is 0.51 (shipped; 21 of 110,925 events below 0.75) and 0.74 (corrected), and 99.9% of events lie above 0.83. The penalty is in the bulk of the error distribution, not the tail — the Kalman's median absolute error is 2.6 times the frozen model's, its 90th to 99.9th percentiles 1.0 to 1.1 times — and removing each arm's worst 1% of events leaves +244 kg of the +257 kg penalty (shipped).
- **Covariance growth over label gaps.** The longest gap between labels is 316 s, so the 3600 s propagation cap is never reached.

What the diagnostics do show is the shape of the error. Against the frozen fit, the observer's line is rotated: its gain is about 6% lower and its offset about 430 kg higher in mass terms, so light vehicles are under-predicted and heavy ones over-predicted while the mean bias is nearly unchanged. Substituting only the observer's offset into the frozen model reproduces +215 kg of the penalty; only its gain, +115 kg. Why the observer settles at that rotation is not established, and we report the penalty as unexplained.

### I. Cost

**FIGURE 13** — `F13__estimator_cost.png`.

**TABLE VI — Per-update cost (bench, x86)**

| Arm | µs/update | State (bytes) |
|---|---:|---:|
| Frozen | 1.44 | 199 |
| RLS | 17.29 | 403 |
| Kalman | 24.24 | 456 |

At the scenario label rate the estimator updates about 22 times per hour: under a millisecond per hour of operation. Computation does not constrain this decision. No embedded benchmark was run.

---

## VI. Discussion

### A. What a drift comparison should report

Our results support a reporting requirement rather than a tuning rule: **an adaptive-versus-static comparison is interpretable only if both the recoverable error and the estimator's memory length are stated.**

Either alone is insufficient. Share fails on S1, where 100% of a 0.9 kg error is recoverable and nothing recovers it. Absolute excess fails on S2, where 2.7 kg is recoverable at one memory length and harmed by another. What the results are consistent with is excess measured against misadjustment, and misadjustment is set by memory length.

Table III shows this most directly: three scenarios, three different optimal settings, ordered by drift character. A benchmark fixing one setting measures that setting, not adaptation.

The magnitudes on S2 are small — under 0.1% of vehicle mass — and no weighing decision turns on them. The point is that the sign of the comparison depends on a setting, and that a reader cannot tell from a single-setting result which side of the reversal it falls on.

This is Widrow's trade-off [CITE-WIDROW] and we claim no novelty in the mechanism. What we add is the measurement: on these scenarios it is large enough to reverse the sign of a result.

Section V-C orders two configuration choices. Specifying the observation noise is worth 0.25–3 kg; choosing the memory length is worth 10–25 kg. The memory should be swept before the noise model is tuned.

### B. Unrepresentative fitting windows are not drift

A model fitted once on a short window carries the window's errors for as long as it is deployed. Here the window contributed two: a thermal displacement worth about −9 kg on the mean vehicle, the same on every seed, and a sampling error from 60 crossings that ranged from −34.5 to +7.8 kg across seeds. Neither decays, and neither is drift.

The practical emphasis is worth inverting. A practitioner inspecting a fitting window for distribution shift should check its **size** first: here the sampling term was both the larger of the two and the one that varied between runs, while the displacement a shift analysis would look for contributed the smaller and more predictable part.

The fitting window should span the deployment conditions and contain enough crossings for its sampling error to be small against the effect being measured, or those conditions should be recorded so the displacement can be estimated; and drift measured as departure from the initial fit will understate error when the initial fit is itself displaced.

### C. Limitations

- **Simulation only.** The floor is not otherwise observable per sample. The generating process is fitted in-sample and not cross-validated.
- **No reference labels were ever physically measured.** No claim about physical weighing accuracy.
- **Floor estimability untested.** We have not shown the floor can be estimated before deployment without ground truth, so the criterion is demonstrated but not shown to be applicable in advance. This is the most consequential gap.
- **The floor counts dynamic load only.** Sensor noise propagated through the feature is not in it, so the excess overstates what any estimator could recover by that amount. An oracle floor using the true time-varying parameters was not computed, because per-sample predictions were not retained.
- A model-class-restricted form of the criterion would require an oracle estimator we did not build.
- **Misadjustment was not measured.** No drift-free control runs were made to measure it directly, and no analytical value is compared against the results. Attributing the S2 reversal to misadjustment is an interpretation consistent with the classical trade-off, not a measurement of it.
- **The memory sweep covers three of seven scenarios** — S2, S4 and S7, chosen to represent gradual, abrupt and sparse-label drift. The ordering of optimal memory length by drift character is established on those three and is not shown to generalise to the remaining four.
- **No survey of reporting practice was conducted.** We do not claim that memory length or noise floors are commonly unreported, only that both are needed to interpret a comparison.
- Hyperparameters other than λ were set on scenarios later used for evaluation.
- Out-of-distribution failures are confounded with difficulty.
- The H1 penalty and the magnitude of the §V-E anti-correlation are unexplained.
- No embedded benchmark.

### D. Reproducibility

Simulator, estimators, configurations, per-run values and analysis scripts at `github.com/martin-hanzely/wim-sim`, DOI `[X]`. The seed protocol was committed before any reported run; Table I values were resolved at the principal sweep's commit and hash-verified. Every comparison that split at ten seeds reports both stages, and each figure carries a sidecar naming its statistic. Provenance details are in Supplementary Note S1.

---

## VII. Conclusion

A comparison between an adaptive and a static model measures the recoverable error minus the misadjustment incurred recovering it. Interpreting one requires both terms, and without them the same scenario can yield opposite conclusions.

Across three scenarios the optimal memory length differs and follows the character of the drift: shortest for abrupt shift, longest for slow drift, intermediate for a gradual ramp with sparse labels. On the slow-drift scenario a short memory is **worse than freezing by 4.13 kg (0.07% of mean vehicle mass)** against only 2.7 kg (0.04%) of recoverable error, while a long memory recovers about half of it. The reversal is under 0.1% of vehicle mass; the finding is that the sign flips, not that the difference matters for weighing. On the abrupt-drift scenario the ordering reverses, a short memory winning by 7.2 kg (0.12%) on 29 of 30 seeds.

Neither the recoverable share nor its absolute magnitude predicts benefit alone — the share fails where the floor is zero, the magnitude fails where the memory is mismatched. Of two configuration choices, memory length is worth roughly ten times more than observation-noise specification.

A memory length tuned on one scenario transferred to one of two out-of-distribution counterparts, beating frozen by 57.8 kg (0.93%) on 10 of 10 seeds. Separately, adaptation reduced median absolute bias from 23.67 kg (0.38%) to 5.74 kg (0.09%) not by tracking drift but by discarding the error of a 60-crossing fitting window — mostly its sampling error, and about 9 kg from its 7.05 °C thermal displacement.

One result resists explanation: on a held-out thermal scenario the Kalman observer is worse than a frozen model by 251 kg (4.0%) as shipped and 264 kg with corrected observation noise. Observation noise, adaptation rate, process noise, instability of the inversion and covariance growth over label gaps are ruled out.

**Future work:** estimating the floor without ground truth, which would make the criterion usable before deployment; a difficulty-matched out-of-distribution draw; and resolving the H1 penalty.

---

## References added in this revision

- [CITE-KRUTCHKOFF] R. G. Krutchkoff, "Classical and inverse regression methods of calibration," *Technometrics*, vol. 9, no. 3, pp. 425–439, 1967.
- [CITE-OSBORNE] C. Osborne, "Statistical calibration: A review," *International Statistical Review*, vol. 59, no. 3, pp. 309–336, 1991.

---

## Appendix A — Figures

| # | File | Status |
|---|---|---|
| 1 | — | to draw |
| 2 | `F2__error_decomposition.png` | regenerated |
| **3** | `F3__forgetting_factor_sweep.png` | **new, primary**; caption reports S2 at λ = 0.99 in its own family |
| 4 | `ladder30__accuracy.png` | unchanged |
| 5 | `F5__effect_sizes.png` | regenerated |
| 6 | `s2__gain_tracking.png` | unchanged |
| 7 | `F7__bias_by_scenario.png` | regenerated |
| 8 | `F8__fitting_window.png` | regenerated; bias stated with its sign (−9.2 kg) |
| 9 | `cintron_ladder30__accuracy.png` | unchanged |
| 10 | `F10__instrument_transfer.png` | regenerated |
| 11 | `heldout30__accuracy.png` | unchanged |
| 12 | `F12__development_vs_heldout.png` | regenerated |
| 13 | `F13__estimator_cost.png` | unchanged |
| 14 | `F14__h1_process_noise.png` | regenerated |

The H1 diagnostics of §V-H are reported in text and data (`export/data/b4_h1_summary.txt`, `export/data/b4_h1_offset_gain.txt`); no figure was added.

---

## Supplementary Note S1 — Provenance

**Run count.** 3,765 simulation runs: 3,670 completed runs across the experiments behind the reported results (`ladder30`, `cintron_ladder30`, `heldout30`, `kalman_q` and every `p1_*` sweep and escalation, partial merges not double-counted), 55 control-arm reruns that reproduced stored sweeps bit for bit before being stopped, and 40 instrumented H1 diagnostic runs.

**Dirty working tree.** Five runs in the memory sweep (S2, λ = 0.95, seeds 26–30) are stamped with a dirty working tree because an analysis script was edited while the queue ran. The simulator and configurations were unchanged against the sweep's commit, and a rerun matched every result field except elapsed time.

**Diagnostic runs.** The 40 H1 diagnostic runs were made at a clean commit with an instrumentation script that records per-event state without altering the run; each run's per-event MAE equals the stored value of the same cell.

---

## Remaining before submission

| Item | Note |
|---|---|
| Reference list | 35–50 entries; all `[CITE-*]` except Krutchkoff and Osborne are placeholders |
| `CITE-BURNOS` | verify the steering-axle attribution before retaining it |
| Misaghi et al. 2021 | source page inaccessible; cite as unverified or drop |
| DOI | Zenodo deposit for the repository |
| Figure 1 | to draw in the venue's figure style |
| AI-use declaration | per venue policy |
| Venue | to be set; adapt length and reference style |
