# CLAUDE.md

## What This Is

Race explanation system — takes a race card and produces structured analysis of each race: pace scenarios, scenario-conditional probabilities, form projections, signal detection, and market comparisons. The output is structured JSON consumed by an LLM to generate contextual narratives.

Reads from `chartbase` PostgreSQL database (same as performance-rating). Consumes the `performance_ratings` table as its primary input.

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
├── running_style.py       # Style classification (E/EP/S/C) from PR history
├── pace_projection.py     # Field composition → 3 scenarios with probabilities
├── conditional_probs.py   # Scenario × horse → win probabilities (lookup + modifiers)
├── form_projection.py     # Recency-weighted, trend-aware ability estimation
├── signals.py             # Detects 7 signal types in PR history
├── past_performances.py   # Full structured PPs (running lines, breeding, connections, PRs)
├── in_running.py          # In-running probability model (P(win | position, lengths, pace))
├── pre_race_projection.py # Monte Carlo pre-race projection using in-running model
├── narrative.py           # Template-based narrative (for CLI, not production)
├── market.py              # Odds comparison (Phase C - stub)
└── db.py                  # Connection helpers
```

## Key Design Decisions

- **Structured output for LLM consumption.** The system produces JSON with scenarios, probabilities, form, signals, and market data. Narrative generation is the LLM's job, not ours.
- **Aligned with chart-parser JSON schema.** Race-level fields (`raceDate`, `track`, `raceNumber`, `distanceSurfaceTrackRecord`, `conditions`, `numberOfRunners`) and starter-level fields (`horse`, `jockey`, `trainer`, `officialPosition`, `pointsOfCall`, `fractionals`, `odds`, `comments`) use chart-parser's naming. Our additions live under an `"analysis"` key at each level.
- **Form projection uses half-life 5 starts** with trip discount. Improves rank correlation by 21% over career average.
- **Signal detection surfaces nuances** the market may miss: shape changes, hidden ability at intermediate calls, pace excuses, closing bursts, style shifts, trajectory changes.
- **Ability multiplier calibrated from data (2026-06-06).** Win probability doubles every 2.7 PR points of advantage over field average (measured from 1.8M starters). The old uncalibrated value was 10.0 — approximately 4× too flat. At +15 PR advantage, a horse wins 64% of the time.
- **The system explains AND predicts.** The A/E curve (Finding 5) shows the market systematically underprices +9 to +30 PR advantage horses (A/E 1.7-2.5). The model's value is in identifying ability edges the market underestimates, particularly dominant horses in weak fields.
- **In-running model is well-calibrated.** Validated across 300 races — when it says 30%, they win ~30%. Provides the building blocks for scenario probabilities.
- **Full structured PPs for LLM context.** The past_performances module produces the equivalent of a Brisnet PP (running lines, breeding, connections, trip comments) enriched with our PR data, signals, and form projection. Gives the LLM everything a handicapper would see.

## Specs & Research

- `docs/race-explanation.md` — full spec
- `docs/implementation-plan.md` — phased plan
- `docs/findings.md` — empirical research findings (market comparison, position prediction, signal value)
