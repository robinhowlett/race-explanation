# Race Explanation System — Implementation Plan

## Project

- **Repo:** `performance-rating` (extending the existing project)
- **Runs on:** robinpc (WSL Ubuntu), via SSH tunnel for local dev
- **Language:** Python 3.12
- **Database:** chartbase (PostgreSQL, `handycapper` schema — same as PR system)
- **Depends on:** `performance_ratings` table (8M rows, already computed)

---

## Phase Overview

```
Phase A: MVP (produces useful explanations from existing data)
  A.1  Build historical lookup tables (win rate by style × pace × distance)
  A.2  Running style classification (position + slope → E/EP/S/C)
  A.3  Pace scenario projection (count speed types → 3 scenarios)
  A.4  Scenario-conditional probabilities (lookup-based)
  A.5  Template narrative generation
  A.6  Validation: backtest pace predictions + probability calibration

Phase B: Calibrated Model (improves accuracy, adds nuance)
  B.1  Pace dependency computation (correlation-based, 8+ starts)
  B.2  Softmax temperature calibration (field-size-dependent)
  B.3  Post position modifiers
  B.4  Scenario-adjusted ability (pace_differential × scenario intensity)
  B.5  Validation: does calibrated model beat MVP lookup?

Phase C: Market Integration (connects to wagering)
  C.1  Odds data pipeline (final odds → implied probabilities)
  C.2  Odds jitter for backtest simulation (±5-10%)
  C.3  Market disagreement identification (model vs market)
  C.4  Edge quantification and confidence
  C.5  Exotic extension (exacta/trifecta scenario probabilities)
```

---

## Phase A: MVP

### A.1 Build Historical Lookup Tables

Pre-compute from the existing `performance_ratings` + `points_of_call` data. These tables become the MVP's probability engine.

**Table 1: Win rate by position quartile × pace bucket × distance zone**

```sql
-- Inputs: performance_ratings, points_of_call, races, starters
-- Output: lookup table (~24 cells: 4 quartiles × 3 pace buckets × 2 zones)
-- Key insight: "front-running horses win X% when pace holds vs Y% when pace collapses"
```

**Table 2: Historical LPD distribution by front_group_size × distance × surface**

```sql
-- Inputs: performance_ratings (lpd, front_group_size), races
-- Output: LPD percentiles conditioned on field composition
-- Key insight: "when 2 speed horses are in the field, LPD is typically -30 to -45"
```

**Table 3: Lone speed bonus / duel penalty**

```sql
-- Inputs: performance_ratings (front_group_size, pr_finish), points_of_call (position=1)
-- Output: empirical bonus for uncontested leaders, penalty for contested
-- Key insight: "lone leaders finish ~4 PR pts higher than contested leaders"
```

**Script:** `scripts/build_race_lookup_tables.py`
**Output:** JSON or pickle files (fast loading at runtime), or DB tables
**Dependencies:** performance_ratings must be populated (already done)

### A.2 Running Style Classification

For each horse entering a race, query their last N starts and compute the style profile.

**Process:**
1. Query performance_ratings + points_of_call for the horse's prior starts (same surface, date < race_date)
2. Compute position_score = median(first_call_position / field_size)
3. Compute slope_type = median(pr_slope)
4. Classify: E/EP/S/C from position_score thresholds
5. Compute ability_estimate = recency-weighted median pr_finish (half-life ~5 starts)
6. Compute avg_pr_2f = mean early speed from pr_2f values
7. Compute pct_in_front_group from front_group membership

**Module:** `src/race_explanation/running_style.py`
**Input:** horse identifier + race_date + surface
**Output:** `RunningStyleProfile` dataclass

**Minimum starts:** 3 for basic classification. Flag confidence as LOW if < 5.
**First-time starters:** Return style_class = "UNKNOWN", ability_estimate = class median for the race's class_level.

### A.3 Pace Scenario Projection

Given the field's style profiles, produce 3 scenarios with probability weights.

**Process:**
1. Count horses with style_class == 'E' and their avg_pr_2f values
2. Determine if pace will be contested (multiple matched speed types)
3. Look up historical scenario probabilities from Table 2 (front_group_size × distance × surface → LPD distribution)
4. Produce 3 PaceScenario objects:
   - Uncontested (LPD > -25): P = f(n_speed, distance)
   - Contested (LPD -25 to -40): P = ...
   - Collapse (LPD < -40): P = ...
5. Assign description ("Horse A on lone lead" / "Horse A and B duel" / "Speed meltdown")

**Module:** `src/race_explanation/pace_projection.py`
**Input:** list of RunningStyleProfiles + race distance + surface
**Output:** list of 3 PaceScenario objects (probabilities sum to 1.0)

### A.4 Scenario-Conditional Probabilities

For each horse under each scenario, compute win probability from the lookup table.

**Process:**
1. For each scenario, determine which LPD bucket it maps to (held/normal/collapse)
2. For each horse, determine their position quartile (from style_class: E=Q1, EP=Q2, S=Q3, C=Q4)
3. Look up base win rate from Table 1: win_rate[quartile][pace_bucket][distance_zone]
4. Scale by relative ability: adjust the base rate by the horse's ability_estimate relative to the field average
5. Normalize across all horses in field so probabilities sum to 1.0

**Module:** `src/race_explanation/conditional_probs.py`
**Input:** list of profiles + list of scenarios + lookup tables
**Output:** dict[horse → dict[scenario → probability]] + overall weighted probability per horse

**Simplification for MVP:** ability adjustment is multiplicative — a horse 10 PR points above field average gets ~2× the base rate for their position/pace cell. Exact multiplier calibrated from data.

### A.5 Template Narrative Generation

Fill structured templates from the computed data.

**Templates:**

Race-level:
```
"{field_size}-horse field at {track} {distance} {surface}. {pace_assessment}."
```

Per-horse (top 4-5 contenders):
```
"{horse} ({prob}%): {style_description}. {best_scenario_text}. {key_risk}."
```

Key contingency:
```
"Key question: {condition}? If yes ({prob}%): {outcome_yes}. If no: {outcome_no}."
```

**Module:** `src/race_explanation/narrative.py`
**Input:** RaceExplanation structured object
**Output:** dict with race_summary, contender_narratives, contingencies as strings

### A.6 MVP Validation

**Pace prediction backtest:**
1. For each race in a held-out year (e.g., 2017):
   - Classify all starters from prior starts only
   - Count E-types → predict scenario
   - Compare predicted LPD range to actual LPD
2. Metrics: rank correlation, calibration of scenario probabilities

**Win probability calibration:**
1. Group races by model's predicted win probability for each horse
2. Check: when model says 20%, do they win ~20%? (reliability diagram)
3. Brier score vs naive baseline (rank by median PR)

**Script:** `scripts/validate_race_explanation.py`
**Baseline comparison:** Does the scenario-weighted model beat a simple "highest PR wins" model?

---

## Phase B: Calibrated Model

### B.1 Pace Dependency

For horses with 8+ starts, compute correlation between LPD and their pr_finish. Store as `pace_correlation` and `pace_differential` in the style profile.

This enables scenario-adjusted ability (a closer with pace_correlation = 0.5 gets boosted in collapse scenarios).

**Depends on:** A.2 (style profiles), adequate start counts
**Validation:** Do pace-dependent horses have higher variance in PR? (They should — their performance is context-dependent.)

### B.2 Softmax Temperature Calibration

Replace the lookup-table-based probabilities with a calibrated softmax:
```
P(horse_i) = exp(adjusted_ability_i / T) / Σ exp(adjusted_ability_j / T)
```

Calibrate T per field_size so top-rated horse wins at the empirically observed rate.

**Process:**
1. For each field size (5-14), find T that produces correct top-horse win rate
2. Store T lookup: {field_size → temperature}
3. Validate: does softmax beat the lookup table on Brier score?

**Depends on:** A.4 (has baseline to beat)

### B.3 Post Position Modifiers

Adjust scenario probabilities (not abilities) based on post position:
- Inside E horse: boost P(uncontested)
- Outside E horse: boost P(contested)

Calibrate from historical data: win rate by PP × style_class × field_size.

**Depends on:** A.3 (scenarios to modify)

### B.4 Scenario-Adjusted Ability

Replace flat lookup rates with ability-based computation:
```
adjusted_ability = base_ability + pace_differential × scenario_intensity + style_bonus/penalty
```

Where:
- `pace_differential` from B.1
- `style_bonus` = lone speed bonus (from Table 3 in A.1)
- `style_penalty` = duel penalty (from Table 3)

**Depends on:** B.1, B.2

### B.5 Phase B Validation

Compare Phase B model to Phase A MVP:
- Same backtest methodology (held-out 2017)
- Does calibrated softmax beat lookup? By how much?
- Does pace_dependency improve conditional probabilities?
- Overall: Brier score improvement, log loss improvement

---

## Phase C: Market Integration

### C.1 Odds Data Pipeline

The `starters.odds` field contains final odds. Convert to implied probabilities:
```
implied_prob = 1 / (odds + 1)    # for decimal odds
```

Handle coupled entries, minus pools, and takeout normalization.

**Depends on:** odds data populated in chartbase (check coverage)

### C.2 Odds Jitter for Simulation

For backtesting, add noise to simulate last-minute betting uncertainty:
- Short-priced (< 3/1): jitter ±5% of implied prob
- Mid-priced (3/1 to 10/1): jitter ±8%
- Longshots (> 10/1): jitter ±12%

This prevents the backtest from exploiting exact closing prices.

### C.3 Market Disagreement

For each horse: `edge = model_prob - market_implied_prob`

Flag disagreements above threshold (e.g., |edge| > 5%). For each disagreement, identify WHICH scenario assumption drives the gap:
- "Model prices collapse at 35%, market implies 15% → closer is overlay"
- "Model sees lone speed, market doesn't seem to discount contested scenario"

**Module:** `src/race_explanation/market.py`

### C.4 Edge Quantification

Beyond identifying disagreements, quantify confidence:
- How stable is the edge across reasonable perturbations of scenario probabilities?
- Is the edge driven by a single scenario (fragile) or present across all scenarios (robust)?

### C.5 Exotic Extension

Extend to multi-horse probabilities:
```
P(A wins, B places) = Σ P(scenario_k) × P(A wins | k) × P(B places | A wins, k)
```

Requires modeling the full finishing order distribution, not just win probability. Use the ability differentials under each scenario to simulate likely finishing orders.

---

## File Structure

```
performance-rating/
├── src/
│   ├── race_explanation/
│   │   ├── __init__.py
│   │   ├── models.py              # Dataclasses (Profile, Scenario, Explanation)
│   │   ├── running_style.py       # Style classification from PR history
│   │   ├── pace_projection.py     # Field → scenarios
│   │   ├── conditional_probs.py   # Scenario × horse → probabilities
│   │   ├── narrative.py           # Structured → text
│   │   └── market.py              # Odds comparison (Phase C)
│   └── ...existing...
├── scripts/
│   ├── build_race_lookup_tables.py    # Pre-compute lookup tables (Phase A.1)
│   ├── explain_race.py                # CLI: explain a specific race by ID or conditions
│   └── validate_race_explanation.py   # Backtest pace + probability predictions
├── data/
│   └── lookup_tables/                 # Pre-computed JSON tables
└── tests/
    └── test_race_explanation.py       # Unit + integration tests
```

---

## Execution Order

Phase A (MVP):
```bash
python scripts/build_race_lookup_tables.py   # A.1: build from existing PR data
# Then for any race:
python scripts/explain_race.py --race-id 298614   # A.2-A.5: classify → project → explain
python scripts/validate_race_explanation.py        # A.6: backtest
```

---

## Estimated Effort

| Phase | Effort | Notes |
|-------|--------|-------|
| A.1 Lookup tables | 1 session | SQL queries + storage |
| A.2 Style classification | 1 session | Query + compute per horse |
| A.3 Pace projection | 1 session | Rule-based from style counts |
| A.4 Conditional probs | 1 session | Lookup + normalization |
| A.5 Narrative | 0.5 session | Templates |
| A.6 Validation | 1-2 sessions | Backtest infrastructure |
| **Phase A total** | **~6 sessions** | |
| B.1-B.5 | 4-5 sessions | Calibration + validation |
| C.1-C.5 | 5-7 sessions | Market integration + exotics |

---

## Key Validation Milestones

| Milestone | Criteria | What it proves |
|-----------|----------|---------------|
| Pace prediction | Rank correlation > 0.3 between predicted and actual LPD | The system correctly identifies which fields will have fast/slow pace |
| Win probability | Brier score < baseline (rank-by-PR) | Scenario conditioning adds value beyond just "best horse wins" |
| Scenario calibration | When P(collapse)=0.3, collapse occurs ~30% | The scenario probabilities are honest |
| Market edge | Positive ROI on flagged overlays over 1000+ race sample | The model identifies genuine mispricing |

---

## Temporal Strict Rules (Leakage Prevention)

1. Style classification for race on date D uses ONLY ratings from races with date < D
2. Lookup tables built from a training window (e.g., 1996-2015). Validation on held-out window (2016-2017).
3. Final odds used as "known at gate-open" — with jitter for simulation realism
4. Today's daily variant NOT available (only computed post-race)
5. No scratches-after-the-fact: use the field as it was at post time
