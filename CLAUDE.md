# CLAUDE.md

## What This Is

Race explanation system — takes a race card and produces structured analysis of each race: pace scenarios, scenario-conditional probabilities, form projections, signal detection, running style profiles, race context base rates, and market comparisons. The output is structured JSON consumed by race-day-sim's Session class and ultimately by an LLM to generate contextual narratives.

Reads from `chartbase` PostgreSQL database. Consumes the `performance_ratings` table as its primary input.

## Setup & Running

```bash
cd race-explanation
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Build lookup tables (once, from existing PR data)
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/build_race_lookup_tables.py

# Explain a single race
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_race_v2.py --track BEL --date 2015-06-06 --number 11

# Explain a full card
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_card.py --track BEL --date 2015-06-06

# JSON output for LLM consumption
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_race_v2.py --track BEL --date 2015-06-06 --number 11 --json

# Validation
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/validate_race_explanation.py
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/validate_in_running.py
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/validate_position_prediction.py
```

## Database

Same chartbase as performance-rating:
```
RE_DB_HOST=localhost
RE_DB_PORT=5433  (via SSH tunnel to robinpc)
RE_DB_NAME=chartbase
RE_DB_USER=handycapper
RE_DB_PASSWORD=handycapper
```

## Architecture

```
src/race_explanation/
├── models.py              # Dataclasses (Profile, Scenario, Signal, FormEstimate, Explanation)
├── running_style.py       # Style classification (E/EP/S/C) + pace dependency + front-group %
├── pace_projection.py     # Field composition → 3 scenarios with calibrated probabilities
├── conditional_probs.py   # Scenario × horse → win probabilities (lookup + ability multiplier)
├── form_projection.py     # Recency-weighted ability: current_level, early/late, trend, last PR
├── signals.py             # Detects 7 signal types in PR history
├── race_context.py        # Base rates: speed/closer win rates, track bias, FTS rate, winner PR dist
├── past_performances.py   # Full structured PPs (running lines, breeding, connections, PRs)
├── connections_context.py # Trainer A/E by dimension, jockey career/track stats
├── in_running.py          # In-running probability model (P(win | position, lengths, pace))
├── pre_race_projection.py # Monte Carlo pre-race projection using in-running model
├── narrative.py           # Template-based narrative (for CLI, not production)
├── market.py              # Odds comparison (stub)
└── db.py                  # Connection helpers
```

## Key Outputs (consumed by race-day-sim)

### Running Style Profile (per horse)
- `style_class`: E / EP / S / C / UNKNOWN
- `slope_type`: Speed / Even / Stamina
- `ability_estimate`: recency-weighted PR (half-life 5 starts)
- `position_score`: median first-call position fraction
- `pct_in_front_group`: fraction of starts in front flight
- `pace_correlation`: correlation between race pace (LPD) and horse's PR (8+ starts)
- `pace_differential`: PR points better under hot pace vs mild (+4.0 = runs 4 better contested)
- `n_starts_used`: sample size for classification confidence

### Form Projection (per horse)
- `current_level`: recency-weighted PR finish (the ability estimate)
- `current_early` / `current_late`: early-speed capability vs finishing ability
- `trend` / `trend_direction`: improving / stable / declining
- `confidence`: 0-1 (from consistency + recency + sample size)
- `last_pr_finish`: most recent PR (for bounce detection)
- `days_since_last`: layoff indicator

### Pace Scenarios (per race)
- 3 scenarios: uncontested, contested, collapse
- Each with calibrated probability and description of which horses create it

### Signals (per horse, 7 types)
- shape_change, hidden_ability, pace_excuse, closing_burst, style_change, improving_trajectory, trouble_discount

### Race Context (per race)
- `speedWinRate` / `closerWinRate`: at this distance/surface
- `trackBias`: speed_favoring / closer_favoring / neutral (vs network average)
- `favoriteWinRate`: at this class/field-size
- `firstTimeStarterWinRate`: for maiden races
- `winnerPRDistribution`: p25/median/p75/p90 of winner PRs at this class

## Key Design Decisions

- **Structured output for LLM consumption.** JSON with scenarios, probabilities, form, signals, and market data. Narrative generation is the LLM's job.
- **Aligned with chart-parser JSON schema.** Race-level and starter-level fields use chart-parser naming. Our additions live under an `"analysis"` key.
- **Form projection uses half-life 5 starts** with trip discount. 21% better rank correlation than career average.
- **Signal detection surfaces nuances** the market may miss: shape changes, hidden ability at intermediate calls, pace excuses, closing bursts, style shifts, trajectory changes.
- **Ability multiplier calibrated from data (2026-06-06).** Win probability doubles every 2.7 PR points of advantage over field average (measured from 1.8M starters). At +15 PR advantage, a horse wins 64% of the time.
- **The system explains AND predicts.** The A/E curve shows the market systematically underprices +9 to +30 PR advantage horses (A/E 1.7-2.5).
- **In-running model is well-calibrated.** Validated across 300 races — when it says 30%, they win ~30%.
- **Full structured PPs for LLM context.** The past_performances module produces the equivalent of a Brisnet PP enriched with PR data, signals, and form projection.

## Consumers

- **race-day-sim** (`session.py`): imports `classify_horse`, `project_form`, `project_pace`, `compute_probabilities`, `detect_signals`, `get_race_context`
- **redboarder** (`server.py`): imports indirectly via race-day-sim's Session class

## Specs & Research

- `docs/race-explanation.md` — full spec
- `docs/implementation-plan.md` — phased plan
- `docs/findings.md` — empirical research findings (market comparison, position prediction, signal value)
