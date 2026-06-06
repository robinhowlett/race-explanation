# Race Explanation System

Produces structured race analysis for an LLM to reason over. For each race: pace scenarios with probabilities, per-horse form projections, signal detection (hidden ability, pace excuses, tactical shifts), and market disagreements.

## What it produces

Structured JSON per race with:
- **Scenarios** — 3 pace scenarios (uncontested / contested / collapse) with probability weights
- **Contenders** — each horse with: win probability, scenario sensitivity, form estimate (level + confidence + trend), running style, and detected signals
- **Market** — model probability vs odds-implied probability, with edge calculation

Example (2015 Belmont Stakes, abbreviated):
```json
{
  "raceDate": "2015-06-06",
  "track": {"code": "BEL"},
  "raceNumber": 11,
  "distanceSurfaceTrackRecord": {"distance": {"compact": "1 1/2m", "feet": 7920}, "surface": "Dirt"},
  "conditions": {"classLevel": "G1"},
  "numberOfRunners": 8,
  "analysis": {
    "scenarios": [
      {"label": "uncontested", "probability": 0.64, "description": "American Pharoah on clear lead"}
    ],
    "contenders": [
      {
        "horse": "American Pharoah",
        "probability": 0.46,
        "scenario_probs": {"uncontested": 0.53, "collapse": 0.18},
        "form": {"current_level": 126, "trend_direction": "declining", "confidence": 0.12},
        "signals": [{"type": "hidden_ability", "description": "Showed PR 128 at 2f but only 116 at finish"}]
      },
      {
        "horse": "Keen Ice",
        "probability": 0.08,
        "scenario_probs": {"uncontested": 0.06, "collapse": 0.16},
        "signals": [
          {"type": "pace_excuse", "description": "Never got pace help in Derby (LPD -6), ran PR 109 but has shown 128"},
          {"type": "closing_burst", "description": "Explosive late move last out — PR 86 early to 106 late"}
        ]
      }
    ],
    "market": [
      {"horse": "Keen Ice", "model_prob": 0.08, "market_prob": 0.05, "edge": 0.03, "odds": 17.2}
    ]
  }
}
```

An LLM consuming this can generate targeted narratives: "tell me about the closers," "who benefits if it rains," "what's the value play."

## Signal Types

The system detects 7 signal types that surface nuances a career average misses:

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
# Setup
pip install -e ".[dev]"

# Build lookup tables (once)
python scripts/build_race_lookup_tables.py

# Single race
python scripts/explain_race_v2.py --track BEL --date 2015-06-06 --number 11 --json

# Full card
python scripts/explain_card.py --track BEL --date 2015-06-06
python scripts/explain_card.py --track BEL --date 2015-06-06 --output-dir output/
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

## Research Findings

See `docs/findings.md` for detailed empirical results. Key takeaways:
- Ability (PR history) is the only predictive signal; style/pace adds narrative but not edge
- The market beats our ability estimate in aggregate — but we're not trying to beat the market flat
- The value is in articulating specific reasons for disagreement: signals + scenarios + form trajectory
- Post position has zero correlation with first-call position on Dirt (conventional wisdom is wrong)

## Past Performances

The system also produces full structured PPs for each horse — the equivalent of what a handicapper sees in a Brisnet PP, enriched with our analytical data:

```json
{
  "horse": {"name": "American Pharoah", "sex": "Colt", "color": "Bay",
            "sire": {"name": "Pioneerof the Nile"}, "dam": {"name": "Littleprincessemma"}},
  "connections": {"trainer": {"firstName": "Bob", "lastName": "Baffert"},
                  "jockey": {"firstName": "Victor", "lastName": "Espinoza"}},
  "record": {"starts": 7, "wins": 6, "winPct": 85.7},
  "analysis": {
    "formProjection": {"currentLevel": 126.1, "trendDirection": "declining", "confidence": 0.12},
    "style": {"class": "E", "slopeType": "Even", "positionScore": 0.167},
    "signals": [{"type": "hidden_ability", "description": "Showed PR 128 at 2f but only 116 at finish"}]
  },
  "pastStarts": [
    {
      "raceDate": "2015-05-02", "track": "CD", "raceNumber": 11,
      "conditions": {"distanceCompact": "1 1/4m", "surface": "Dirt", "classLevel": "G1"},
      "officialPosition": 1, "odds": 2.9,
      "jockey": {"firstName": "Victor", "lastName": "Espinoza"},
      "pointsOfCall": [{"compact": "2f", "feet": 1320, "relativePosition": {"position": 3, "totalLengthsBehind": 1.0}}],
      "comments": "5wd turns,brushed late",
      "analysis": {
        "performanceRating": {"finish": 115.9, "early": 121.6, "late": 117.2, "slope": -2.22},
        "pace": {"lpd": -5.6, "frontGroupSize": 14},
        "context": {"dailyVariant": 0.53}
      }
    }
  ]
}
```

An LLM consuming this has everything needed to reason about a horse's history — where they were at every point in every race, how fast they ran, what went right or wrong, and our analytical signals on top.

## Architecture

Depends on the `performance-rating` system's output (`handycapper.performance_ratings` table with 8M rows).

```
performance-rating/ → computes PRs (backward-looking, batch)
race-explanation/   → consumes PRs, produces explanations (forward-looking, per-race)
```
