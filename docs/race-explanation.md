# Race Explanation System — Spec

## Purpose

Given a specific race with entered horses, produce a structured explanation of:
1. How the race is likely to unfold (pace scenario)
2. What chance each horse has and WHY
3. What scenarios favor/hurt each horse
4. Where the model disagrees with the market

Consumes: `performance_ratings` (PR history per horse), race conditions (from card), field composition
Produces: structured race analysis with scenario-conditional probabilities and natural-language narrative

---

## Design Principles

1. **Field-level, not horse-level.** You can't project one horse without knowing who they're running against. The pace scenario emerges from the combination of running styles in the field.

2. **Scenario-based.** A single probability per horse is insufficient. The system produces conditional probabilities: "if the pace collapses, Horse B wins 35%; if pace holds, Horse A wins 45%." The overall probability is the weighted average across scenarios.

3. **Explainable.** Every probability must have a reason. The output isn't just numbers — it's "why" in natural language. The system must articulate the key contingencies that determine the race outcome.

4. **Market-aware.** The system compares its probabilities to market-implied probabilities (from odds) and identifies disagreements. The wagering value is in the disagreements, not the projections themselves.

5. **Temporal strict.** Running style classification uses ONLY starts before the race date. No future leakage.

---

## Architecture

```
[1. Running Style Profile]    ← horse's prior PR history
        ↓
[2. Pace Scenario Projection] ← field composition + style profiles
        ↓
[3. Scenario-Conditional Probabilities] ← each horse × each scenario
        ↓
[4. Narrative Generation]     ← structured → English
```

---

## Component 1: Running Style Classification

For each horse entering the race, classify their preferred running position, energy distribution, and pace sensitivity from their last N rated starts (N=5 minimum, up to 10).

### Data Inputs

From `performance_ratings`:
- `pr_2f` — early speed capability
- `pr_early`, `pr_late` — first-half vs second-half performance
- `pr_slope` — energy distribution shape
- `pr_finish` — overall ability level
- `lpd` — pace context of each past race (what scenario they experienced)
- `front_group_size` — whether they were part of the pace
- `positional_gain` — how much they move through the race

From `points_of_call`:
- Position at first call (point 2) — where they were early
- `tot_len_bhd` — how far behind

### Dimensions

**A. Position Preference**

```
position_score = median(position_at_first_call / field_size)
```

| Classification | Position Score | Description |
|---|---|---|
| E (Early / Lead) | ≤ 0.20 | Typically 1st or 2nd |
| EP (Early Presser) | 0.20 – 0.40 | Just off the pace, 2nd-3rd |
| S (Stalker) | 0.40 – 0.65 | Mid-pack |
| C (Closer) | > 0.65 | Back of the pack |

Supplemented by: percentage of starts where horse was in the front group.

**B. Energy Distribution**

```
slope_type = median(pr_slope over last N starts)
```

| Classification | Median Slope | Description |
|---|---|---|
| Speed | < -3.0 | Early superiority evaporates through race |
| Even | -3.0 to +3.0 | Consistent effort relative to par |
| Stamina | > +3.0 | Outperforms par by increasing margin (fades less than expected) |

**C. Pace Dependency** (requires 8+ starts)

```
pace_correlation = pearson_r(lpd, pr_finish)  across horse's starts
```

| Correlation | Interpretation |
|---|---|
| > +0.3 | Benefits when pace collapses (pace-dependent closer) |
| < -0.3 | Benefits when pace holds (pace-dependent speed horse) |
| -0.3 to +0.3 | Pace-neutral — performs similarly regardless |

Additionally, split their PR into hot-pace starts (LPD < -30) vs mild-pace starts (LPD > -20):
```
pace_differential = mean(pr_finish WHERE lpd < -30) - mean(pr_finish WHERE lpd > -20)
```

Large positive differential = much better in fast-pace races.

**D. Tactical Versatility**

```
versatility = std(position_at_first_call / field_size)
```

High versatility (std > 0.15) = horse can adapt position. Low (std < 0.08) = one-dimensional.

### Edge Cases

- **First-time starters (no PR history):** Style = UNKNOWN. High uncertainty in all scenarios. Default to class-average position distribution.
- **Limited starts (1-4):** Can compute position_score and slope. Cannot compute pace_correlation. Mark pace as neutral with high uncertainty.
- **Surface switches:** Only use same-surface starts. If insufficient, fall back to all starts with reduced confidence flag.

### Output

```python
RunningStyleProfile:
    horse: str
    style_class: str          # E, EP, S, C
    slope_type: str           # Speed, Even, Stamina
    position_score: float     # 0-1 (lower = more forward)
    median_slope: float       # PR points
    pace_correlation: float   # -1 to +1 (null if < 8 starts)
    pace_differential: float  # PR points (null if < 8 starts)
    versatility: float
    ability_estimate: float   # recency-weighted median pr_finish
    n_starts_used: int
    pct_in_front_group: float
    avg_pr_2f: float          # early speed capability
```

---

## Component 2: Pace Scenario Projection

Given the field's style profiles, project what pace scenario will likely develop.

### Step 2.1: Identify Speed Presence

Count and rank E-type horses by early speed ability:
```
n_speed = count(profiles WHERE style_class == 'E')
speed_quality = sorted(avg_pr_2f of E horses, descending)
```

Also count EP horses who may contest if the pace is slow.

### Step 2.2: Scenario Classification

| n_speed | Context | Scenario | Expected LPD |
|---|---|---|---|
| 0 | No speed in field | Slow / no pace | > -15 |
| 1 | Dominant (pr_2f > field avg + 10) | Lone speed, comfortable | -18 to -25 |
| 1 | Moderate ability | Uncontested, moderate pace | -22 to -28 |
| 2 | Similar ability (diff < 5 pts) | Contested duel | -30 to -45 |
| 2 | One dominant (diff > 8 pts) | Briefly contested, then lone | -25 to -35 |
| 3+ | Multiple pressing | Speed meltdown / collapse | -40 to -55+ |

### Step 2.3: Post Position Modifier

Post position affects the ability to execute preferred style:
- Inside speed horse (PP 1-3): higher probability of establishing lead uncontested
- Outside speed horse (PP 8+ in sprint): must use more energy, contested scenario more likely
- Route races: PP effect diminishes (more time to settle)

Post position modifies scenario probabilities, not ability estimates.

### Step 2.4: Produce Three Scenarios

```python
PaceScenario:
    label: str           # "uncontested", "contested", "collapse"
    expected_lpd: float  # center of expected LPD range
    probability: float   # 0-1, how likely
    description: str     # "Horse A on uncontested lead"
```

Sum of probabilities across scenarios = 1.0.

### Calibration

Scenario probability tables are calibrated from historical data:
```sql
-- Historical LPD distribution by front_group_size × distance × surface
SELECT front_group_size, distance_compact, surface,
       PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY lpd) as lpd_p25,
       PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY lpd) as lpd_median,
       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY lpd) as lpd_p75,
       COUNT(DISTINCT race_id) as n_races
FROM handycapper.performance_ratings
WHERE lpd IS NOT NULL AND front_group_size IS NOT NULL
GROUP BY 1, 2, 3
```

### Validation

Backtest: for every race, classify styles from PRIOR starts only, predict LPD, compare to actual. Target: rank correlation > 0.3, calibrated scenario probabilities.

---

## Component 3: Scenario-Conditional Probabilities

### Step 3.1: Scenario-Adjusted Ability

For each horse under each scenario, adjust their baseline ability:

```
adjusted_ability = ability_estimate + pace_adjustment + style_bonus/penalty
```

Where:
- **pace_adjustment** = pace_differential × scenario_intensity (closers get boosted in collapse scenarios, speed horses get boosted in uncontested)
- **style_bonus**: lone speed in uncontested scenario gets empirical bonus (~3-5 PR pts from data); speed in contested duel gets penalty

Calibration constants derived from:
```sql
-- Lone speed bonus: pr_finish of position-1 horses when front_group_size = 1 vs > 1
-- Speed duel penalty: pr_finish of position-1 horses when front_group_size >= 2
```

### Step 3.2: Abilities → Win Probabilities

Calibrated softmax (multinomial logit):

```
P(horse_i wins) = exp(adjusted_ability_i / T) / Σ exp(adjusted_ability_j / T)
```

Temperature T calibrated by field size so that the top-rated horse wins at the empirically observed rate (~35% in 8-horse fields, ~25% in 12-horse fields).

### Step 3.3: Overall Probability

```
P(horse wins) = Σ P(scenario_k) × P(horse wins | scenario_k)
```

### Step 3.4: Scenario Sensitivity

```
sensitivity = max(P across scenarios) - min(P across scenarios)
```

High sensitivity = pace-dependent horse whose chances swing dramatically based on how the race is run.

---

## Component 4: Narrative Generation

### Race-Level

```
"[N]-horse field at [track] [distance] [surface].
[Pace assessment]: [speed horses] figure to contest the early lead,
suggesting [contested/fast pace scenario] is most likely ([probability]%).
This [benefits closers / favors speed / is neutral]."
```

### Per-Horse

```
"[HORSE] ([probability]%): [Style] who [key strength].
Best scenario: [description] ([probability in that scenario]%).
Key risk: [what could go wrong].
[If high sensitivity]: Chances range from [min]% to [max]% depending on pace."
```

### Key Contingencies

```
"The key question: [Will the speed duel materialize?]
If yes ([probability]%): [beneficiaries] become live at [boosted odds].
If no ([probability]%): [speed horse] likely controls."
```

### Market Disagreement

```
"[HORSE]: Model [probability]% vs market [implied probability]% = [overlay/underlay].
Reason: [which scenario assumption drives the gap]."
```

---

## Output Schema

```python
RaceExplanation:
    race_id: int
    field_size: int
    pace_summary: str
    scenarios: list[PaceScenario]        # 3 scenarios with probabilities
    
    contenders: list[ContenderAnalysis]   # All horses, ordered by overall prob
    key_contingencies: list[Contingency]  # 2-3 pivotal "if/then" questions
    market_disagreements: list[Disagreement]

ContenderAnalysis:
    horse: str
    overall_prob: float
    style_profile: RunningStyleProfile
    scenario_probs: dict[str, float]     # probability under each scenario
    sensitivity: float
    best_scenario: str
    worst_scenario: str
    narrative: str

Contingency:
    condition: str         # "If Horse A and B duel"
    probability: float     # P(this condition)
    beneficiaries: list[str]
    outcome: str

Disagreement:
    horse: str
    model_prob: float
    market_prob: float
    edge: float            # model - market
    reason: str            # "pace collapse underpriced"
```

---

## MVP Implementation

The minimum useful version that produces race explanations:

### What's in MVP
1. Running style classification (position score + slope type → E/EP/S/C)
2. Simple pace scenario from speed count (rule-based, 3 scenarios)
3. Historical conditional win rates as lookup table (no softmax calibration)
4. Template-based narrative from structured output

### What's deferred
- Pace_correlation (needs 8+ starts per horse — Phase B)
- Post position modifiers (Phase B)
- Calibrated softmax temperature (Phase B)
- Market comparison (requires odds data pipeline — Phase C)
- LLM-enhanced narrative (Phase C)
- Multi-surface style profiles (Phase C)

### MVP Data Requirements

Pre-compute one lookup table:
```sql
-- Win rate by (position_quartile × pace_bucket × distance_zone)
-- This IS the probability model for MVP
```

Then for each race:
1. Query each horse's last 5 starts → classify style
2. Count E-types in field → select scenario probabilities
3. For each horse × scenario: look up conditional win rate from table
4. Weight by scenario probabilities → overall probability
5. Fill templates → narrative

---

## Temporal Ordering & Leakage Prevention

### What's known when

The system operates at a specific moment: **just before the gates open**. Information availability:

| Data | When known | How to use |
|------|-----------|-----------|
| Horse's prior PR history | Published post-race for all PRIOR starts | Use freely — this is the core input |
| Race conditions (track, distance, surface, class) | Known at entry/draw time (~days before) | Use freely |
| Field composition (who's entered) | Known at entry time, may change with scratches | Use the final field |
| Post positions | Known at draw (~days before) | Use freely |
| Jockey/trainer | Known at entry | Use freely |
| Equipment/medication changes | Known at entry | Use freely |
| Morning line odds | Published day before or morning of | Use as early market signal |
| Final odds / pool sizes | Known at gates open — but published AFTER the race | See below |
| Actual race outcome | Post-race | NEVER available to the system — this is what we're predicting |

### Final odds and pool sizes

The final odds and pool sizes represent the market's collective opinion at the moment of the race. In a live wagering context, you'd see approximate odds up to the last minute. In a backtest using historical data, the exact final odds are technically "post-race published" — but they reflect pre-race information (bettors' opinions before the gates open).

**Design decision:** For backtesting, use the final odds/pools as if they were known. They represent the information state at gate-open, even though the exact values are settled by the closing of betting. The system compares its probabilities AGAINST these odds to find edge.

**For simulation of live wagering:** Add noise to the final odds to simulate the uncertainty of betting in the last minute:
- Odds jitter: ±5-10% on the implied probability (short-priced horses are more stable; longshots fluctuate more)
- Pool size uncertainty: ±10% of final pool (early in the sequence pools are smaller; late pools more certain)

This prevents the backtest from having "perfect" market information that a real bettor wouldn't have.

### Strict leakage rules

1. **Running style classification** for a race on date D uses ONLY performance_ratings from races with `date < D`. Never the current race.
2. **Pace scenario projection** uses style profiles built from prior data only.
3. **Calibration tables** (win rates by style × pace, softmax temperature, etc.) are built from a SEPARATE time window or cross-validated — never from the same race being predicted.
4. **Daily variant** from the current card is NOT known before the race — the system cannot use today's DV in the projection. Today's DV is only available post-race for rating purposes.

---

## Relationship to Other Systems

| System | Relationship |
|--------|-------------|
| Performance Rating | Race explanation CONSUMES PR history. Never modifies it. |
| Form Projection | Race explanation subsumes form projection — it IS the forward-looking prediction, but conditional on field composition rather than static. |
| Wagering | Wagering CONSUMES race explanations. Uses disagreements to identify bet opportunities. |

---

## Validation

### Pace Prediction
- Predict LPD from field composition (prior-starts-only classification)
- Compare to actual LPD
- Target: rank correlation > 0.3

### Win Probability Calibration
- Brier score / log loss against actual outcomes
- Reliability diagram: when model says 20%, do they win ~20%?
- Comparison to naive baseline (rank by median PR_finish)

### Narrative Quality
- Run on 50 known stakes races with documented pace dynamics
- Verify: style classifications match consensus, pace projections identify known duels, beneficiary identification correct

---

## Open Questions

1. **Distance conditioning.** Should style classification be distance-specific? A horse might be E at 6f but S at 1 1/16m. With limited starts at each distance, splitting thin.

2. **Trainer patterns as pace signal.** Some trainers always send (speed) or always sit (stalk). Should trainer be a factor in pace projection?

3. **Jockey style interaction.** Same horse with different jockeys may run different positions. How much does jockey override horse style?

4. **Weather/track condition effect on pace.** Wet tracks generally slow early pace. Should the scenario probabilities adjust for track condition?

5. **How many scenarios?** Three (uncontested/contested/collapse) may be too coarse. Some races have a "one horse breaks clear of a pack" dynamic that doesn't fit neatly.

6. **Exacta/trifecta extension.** The system naturally extends to exotic projections: P(A wins AND B places) = Σ P(scenario) × P(A wins | scenario) × P(B places | A wins, scenario). Worth designing from the start?
