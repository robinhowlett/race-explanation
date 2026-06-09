# Race Explanation System

Produces structured race analysis for an LLM to reason over. For each race: pace scenarios with probabilities, per-horse form projections (ability + early/late + trend), running style profiles (with pace dependency), signal detection (7 types), race context base rates, and market comparisons.

## What It Produces

Structured JSON per race with:
- **Scenarios** — 3 pace scenarios (uncontested / contested / collapse) with calibrated probability weights
- **Contenders** — each horse with: win probability, scenario sensitivity, form estimate (level + early/late + confidence + trend + last PR), running style (class + pace dependency + front-group %), and detected signals
- **Race Context** — base rates: speed/closer win rates at this distance/surface, track bias, favorite win rate, FTS win rate
- **Market** — model probability vs odds-implied probability vs Benter-combined, with edge calculation

## Signal Types

| Signal | What it means |
|--------|--------------|
| `hidden_ability` | High PR at intermediate call, moderate finish — has speed but couldn't sustain |
| `pace_excuse` | Compromised by impossible pace scenario (front-runner in collapse, closer in held pace) |
| `closing_burst` | Explosive late move (PR_late >> PR_early) — finishing kick on display |
| `shape_improving` | Energy distribution getting better — fading less, or building more |
| `style_change` | Tactical shift from established pattern (moved forward or back) |
| `improving_trajectory` | Steadily rising PR across recent starts |
| `trouble_discount` | Trip trouble suppressed PR below clean average |

## Running

```bash
pip install -e ".[dev]"

# Build lookup tables (once)
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/build_race_lookup_tables.py

# Single race (JSON output for LLM consumption)
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_race_v2.py --track BEL --date 2015-06-06 --number 11 --json

# Full card
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_card.py --track BEL --date 2015-06-06
```

Requires `RE_DB_HOST` and `RE_DB_PORT` env vars pointing to the chartbase PostgreSQL database.

## Validation Results

| Metric | Value |
|--------|-------|
| Top-pick win rate | 25.6% (2.2× random) |
| Rank correlation (form projection) | 0.287 |
| Rank correlation (market/odds) | 0.470 |
| In-running calibration | ✓ at all probability levels (300 races) |
| Brier improvement vs naive | 19.7% |
| Consistent across Dirt/Turf/Synthetic | ✓ (0.28 correlation on all surfaces) |

## Key Design Decisions

- **Ability multiplier = 2.7 PR points** (calibrated from 1.8M starters). Win probability doubles every 2.7 points of advantage.
- **Form uses half-life 5 starts** with trip discount. 21% better rank correlation than career average.
- **Pace dependency quantified per horse.** `pace_correlation` and `pace_differential` tell you exactly how much a horse benefits from contested pace.
- **Race context provides calibration.** Speed wins X% here, closers win Y% — grounds pace analysis in base rates.
- **A/E curve shows market inefficiency** at +9 to +30 PR advantage (A/E 1.7-2.5). The system identifies ability edges the market underestimates.

## Architecture

```
performance-rating/ → computes PRs (backward-looking, batch, 8M rows)
race-explanation/   → consumes PRs, produces explanations (forward-looking, per-race)
race-day-sim/       → consumes explanations via Python imports (Session class)
redboarder/         → exposes via web API + LLM conversation
```

## Related Projects

- [race-day-sim](https://github.com/robinhowlett/race-day-sim) — orchestration (Session class, opinion classification, market combination)
- [redboarder](https://github.com/robinhowlett/redboarder) — web app (Next.js + Claude API)
- [racing-stats](https://github.com/robinhowlett/racing-stats) — trainer/jockey A/E snapshots
- [wagering-analytics](https://github.com/robinhowlett/wagering-analytics) — EV evaluation, Stern-Harville
- [bet-calculator](https://github.com/robinhowlett/bet-calculator) — ticket construction
