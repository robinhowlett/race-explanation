# Performance Rating (PR) — Reference

## What PR Is

A speed rating for every horse in every race, measuring how fast they ran relative to what a baseline-class horse would be expected to run at that specific track, distance, surface, and call point — on that specific day.

It is NOT a raw speed figure. It is a normalized, context-adjusted measurement that allows comparison across tracks, distances, and days.

## The Scale

| PR | Meaning |
|---:|---------|
| 128+ | G1 level (the best racehorses) |
| 123 | G2 level |
| 120 | G3 level |
| 116 | Listed stakes |
| 112 | CLM $50K |
| 108 | CLM $20K |
| 105 | Allowance / CLM $10-20K |
| **100** | **CLM $5K level (the Dirt/Synthetic anchor)** |
| **110** | **CLM $20K level (the Turf anchor)** |
| 97 | CLM <$5K |
| 94 | Maiden Claiming $10K |
| 90 | Maiden Claiming <$10K |

The scale is universal: PR 120 means "G3 level performance" whether earned at Santa Anita, Belmont Park, or Mountaineer — on Dirt or Turf.

## How It's Computed

For each fractional call point in a race:

```
PR = anchor_PR + (horse_fps - day_adjusted_par) / scale_factor
```

Where:
- **horse_fps** = the horse's individual speed (feet per second) at that call, derived from leader time + lengths behind
- **day_adjusted_par** = what a baseline-class horse is expected to run at this track/distance/surface/call, adjusted for how fast the track played today
- **scale_factor** = how many fps equals 1 PR point at this track (varies by track — compressed tracks like SA have smaller scale, spread tracks like MNR have larger)
- **anchor_PR** = 100 for Dirt/Synthetic, 110 for Turf

## What Gets Normalized Away

The PR system removes these factors so the number is purely about the horse's performance:

| Factor | How it's handled |
|--------|-----------------|
| Track speed (SA is faster than MNR) | Track-specific par + shipping-graph offset |
| Distance (6f is faster fps than 1m) | Distance-specific par at each call |
| Surface (Turf vs Dirt vs Synthetic) | Surface-specific anchors and par curves |
| Track condition (Fast vs Muddy) | Only Fast/Firm races are rated |
| Day-to-day variation (track plays fast today) | Daily variant adjustment from the card |
| Field quality (G1 fields are faster) | Compared to a fixed anchor class, not to the race's own class |

## The PR Vector

Each horse gets a PR at every available call point in the race. A 6f race typically produces:

```
[PR_2f, PR_4f, PR_5f, PR_6f(finish)]
```

A 1m race might produce:

```
[PR_2f, PR_4f, PR_6f, PR_7f, PR_1m(finish)]
```

The vector shows how the horse's performance evolved through the race relative to par at each point.

## Key Fields

| Field | What it means |
|-------|--------------|
| `pr_finish` | PR at the last available call — the horse's overall performance level |
| `pr_early` | Average PR across the first half of calls — early speed |
| `pr_late` | Average PR across the second half — finishing ability |
| `pr_slope` | Linear trend across calls — positive = outperformed par by increasing margin (stamina signature), negative = early advantage evaporated (speed signature) |
| `lpd` | Leaders' Pace Delta — how much the front-runners declined from start to finish. Negative = leaders faded. LPD < -40 = pace collapsed (benefits closers) |
| `daily_variant_fps` | How much faster/slower the track played today vs normal. Positive = fast day. Already baked into the PR (par was shifted). |
| `daily_variant_std` | Consistency of the daily variant signal. High std = uncertain whether the track was truly fast/slow or just mixed results. |
| `front_group_size` | How many horses set the pace (1 = lone speed, 3+ = contested) |
| `positional_gain` | Positions moved from first call to finish (positive = closed, negative = faded back) |
| `trip_flags` | Trouble in running: steadied, checked, bumped, blocked, wide, geared_down |

## What pr_slope Does NOT Mean

A positive `pr_slope` does NOT mean the horse accelerated in absolute terms. It means they outperformed the par expectation by an increasing margin through the race.

Example: American Pharoah in the 2015 Belmont Stakes:
- Actual fps: 54.86 (2f) → 54.07 (4f) → 53.88 (1m) → 54.01 (1½m finish)
- He slowed down in absolute terms.
- But the par EXPECTED him to slow down more: 52.60 (2f) → 52.69 (4f) → 52.39 (1m) → 51.15 (1½m)
- His deviation from par GREW: +2.26 → +1.38 → +1.49 → +2.86
- That growing deviation = positive pr_slope = "stamina signature"

A horse with pr_slope = +5 is a stayer who holds speed better than expected. A horse with pr_slope = -5 is a speed type whose early superiority evaporates.

## Daily Variant

The daily variant measures how fast the track surface played on a given day by comparing the field's actual speed to class-adjusted expectations across all races on the card.

- `daily_variant_fps = +0.5` means the card ran 0.5 fps above normal — it was a "fast" day
- This is ALREADY subtracted from the PR (the par was shifted up by 0.5 before computing PR)
- So a PR of 110 on a +0.5 day is a genuine PR 110 — the fast track was accounted for
- `daily_variant_std = 0.3` means the signal was consistent (all races agreed the track was fast)
- `daily_variant_std = 1.2` means the card was mixed — some races ran fast, others normal

## Confidence Considerations

PRs are more trustworthy when:
- The par was from direct data (not model interpolation)
- The daily variant was based on 5+ races with low std
- The horse completed the race without trouble (no trip flags)
- The track/distance has abundant historical data

PRs are less trustworthy when:
- The par came from the continuous model (rare distances, sparse tracks)
- The daily variant was based on only 3 races with high std
- The horse was compromised by trouble (steadied, blocked)
- The track is tiny with inverted class ladders (DUE, ANF, LBG)

## How PR Feeds the Race Explanation System

The race explanation system uses PR history to:
1. **Estimate current ability** — recency-weighted average of recent pr_finish values (half-life 5 starts)
2. **Classify running style** — from position history and pr_slope patterns (E/EP/S/C)
3. **Detect signals** — shape changes, hidden ability at intermediate calls, pace excuses, closing bursts
4. **Project pace** — from early speed capability (pr_2f relative to field)
5. **Compute scenario probabilities** — combining ability, style, and pace context
