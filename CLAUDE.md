# CLAUDE.md

## What This Is

Race explanation system — takes an entered field and produces a structured analysis of how the race will likely unfold, what each horse's chances are under different pace scenarios, and where the model disagrees with the market.

Reads from `chartbase` PostgreSQL database (same as performance-rating). Consumes the `performance_ratings` table as its primary input.

## Setup & Running

```bash
cd race-explanation
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Build lookup tables (once, from existing PR data)
python scripts/build_race_lookup_tables.py

# Explain a specific race
python scripts/explain_race.py --race-id 298614

# Validate
python scripts/validate_race_explanation.py
```

## Database

Same as performance-rating:
```
RE_DB_HOST=localhost
RE_DB_PORT=5432  (or 5433 via SSH tunnel)
RE_DB_NAME=chartbase
RE_DB_USER=handycapper
RE_DB_PASSWORD=handycapper
```

## Architecture

```
src/race_explanation/
├── models.py              # Dataclasses (Profile, Scenario, Explanation)
├── running_style.py       # Style classification from PR history
├── pace_projection.py     # Field → 3 scenarios with probabilities
├── conditional_probs.py   # Scenario × horse → win probabilities
├── narrative.py           # Structured → text
├── market.py              # Odds comparison (Phase C)
└── db.py                  # Connection helpers
```

## Specs & Context

- `docs/race-explanation.md` — full spec
- `docs/implementation-plan.md` — phased plan
- Performance rating spec: `../performance-rating/docs/performance-rating-system.md`
