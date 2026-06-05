# Race Explanation System

Takes an entered field of horses and produces a structured analysis: how the race will likely unfold, what each horse's chances are under different pace scenarios, and why.

## What it produces

For any race in the database, the system outputs:

1. **Pace scenario projection** — will the speed be contested? 3 scenarios with probability weights.
2. **Scenario-conditional probabilities** — each horse's win chance under each scenario.
3. **Narrative explanation** — natural language: who benefits from what, what the key contingency is.

Example output (2015 Belmont Stakes):
```
8-horse field at BEL 1 1/2m Dirt. American Pharoah figures to control on a clear lead.

Most likely scenario (64%): American Pharoah figures to control on a clear lead.

CONTENDERS:
1. American Pharoah (46%): Front-runner with even energy distribution.
   Chances range from 18% (collapse) to 52% (uncontested).
2. Frosted (14%): Stalker with even energy distribution.
3. Keen Ice (8%): Closer who finishes strongly.
   Chances range from 6% (uncontested) to 16% (collapse).

Key question: Does American Pharoah get an uncontested lead?
If yes: American Pharoah is dangerous on an easy lead.
If challenged by Frosted: pace quickens, opening the door for closers.

ACTUAL RESULT: #1 American Pharoah, #2 Frosted, #3 Keen Ice ✓
```

## How it works

1. **Running Style Classification** — queries each horse's last 5-10 rated starts, computes position preference (E/EP/S/C), energy distribution (Speed/Even/Stamina), and ability estimate.

2. **Pace Scenario Projection** — counts speed types in the field, determines if pace will be contested, produces 3 scenarios with probabilities.

3. **Conditional Probabilities** — for each horse × scenario, looks up historical win rates by position-quartile × pace-bucket, scaled by relative ability and style×scenario interaction.

4. **Narrative** — fills templates from structured output.

## Running

```bash
cd race-explanation
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Build lookup tables (once)
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/build_race_lookup_tables.py

# Explain a race
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_race.py --track BEL --date 2015-06-06 --number 11
RE_DB_HOST=localhost RE_DB_PORT=5433 python scripts/explain_race.py --race-id 298614
```

## Database

Reads from the same `chartbase` PostgreSQL database as the performance-rating system. Requires the `performance_ratings` table to be populated.

```
RE_DB_HOST=localhost
RE_DB_PORT=5433  (via SSH tunnel to robinpc)
RE_DB_NAME=chartbase
RE_DB_USER=handycapper
RE_DB_PASSWORD=handycapper
```

## Validation Results (MVP)

| Race | Model Top Pick | Actual Winner | Top 3 Match? |
|------|---------------|---------------|---|
| 2015 Belmont Stakes (G1) | American Pharoah (46%) | American Pharoah | Yes — 1,2,3 exact |
| SA 2014 Frank E. Kilroe Mile (G1) | Winning Prize (21%) | Winning Prize | Winner correct |
| SAR 2017 Schuylerville (G3, pace collapse) | Mel's Gone Wild (28%) | Dream It Is (#2, 20%) | Actual winner was 2nd choice |

## Docs

- `docs/race-explanation.md` — full spec
- `docs/implementation-plan.md` — phased plan (MVP → Calibrated → Market)

## What's next

- **Phase B**: Pace dependency (correlation-based), softmax temperature calibration, post position modifiers
- **Phase C**: Odds integration, market disagreement identification, exotic extension
