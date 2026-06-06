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
6. **Produce structured past performances** — full PP with running lines, PRs, pace context, and trip comments for each prior start

## How to Communicate These Numbers

The structured data contains precise values. When generating narratives, translate them into racing language that a knowledgeable fan would use — grounded in the numbers but not dominated by them.

### PR Finish (ability level)

| Instead of | Say something like |
|---|---|
| "PR 126.1" | "a form figure of 126 — solidly at G1 level, among the best in this field" |
| "PR 103" | "running at a solid mid-level claiming figure" |
| "PR 95" | "below average for this class — likely overmatched" |

Context that helps: compare to the field. "His best recent figure of 118 would make him competitive here, where the field averages around 112." Or: "At 126 he's head and shoulders above this lot — the next best is only 114."

When a horse has earned a PR that's above their current class level: "He's been running G3 figures (120+) while entered in allowance company — either he's improving or his trainer is protecting him at a lower level."

### PR Slope (energy distribution)

| Instead of | Say something like |
|---|---|
| "slope +5.2" | "a strong finishing type who saves his best for late — his figures get better as the race goes on relative to par" |
| "slope -4.0" | "a front-end type who uses his speed early but tends to flatten out in the final stages" |
| "slope +0.5" | "distributes his energy evenly throughout — not obviously one-dimensional" |

The key: slope is RELATIVE TO PAR, not absolute acceleration. A positive slope doesn't mean the horse speeds up — it means they hold their speed better than the expected deceleration curve. The right phrasing:

- Positive slope: "finishes stronger than expected for this distance" or "his advantage over par grows through the race — a stamina signature"
- Negative slope: "his early superiority tends to evaporate as the race progresses" or "he's at his most dangerous in the first half"
- Near zero: "runs to a consistent level throughout" or "no obvious bias between early and late"

### LPD (Leaders' Pace Delta)

LPD measures how much the front-runners declined from the first call to the finish. It tells you what HAPPENED to the pace, not what should have happened.

| LPD | What happened | How to describe it |
|---|---|---|
| > -15 | Leaders barely faded | "the pace was pedestrian — front-runners had it easy and coasted home" |
| -15 to -25 | Normal deceleration | "an honest pace that neither helped nor hurt the speed" |
| -25 to -35 | Notable fade | "the pace took its toll — leaders came back to the field in the stretch" |
| -35 to -48 | Heavy decline | "a punishing pace that set it up perfectly for closers" |
| < -48 | Collapse | "the pace utterly collapsed — the speed horses destroyed each other, and anything coming from behind was gifted the race" |

In narrative: "Last time out, the pace collapsed (LPD -52) and he was the main beneficiary, rallying from 8 lengths back to win going away. The question is whether he can reproduce that figure when the pace is more honest — his two runs on a held pace (LPD -12, -18) yielded much lower figures."

### Daily Variant

| Instead of | Say something like |
|---|---|
| "daily_variant +0.8" | "the track was playing fast that day — about 0.8 fps faster than normal, which inflated everyone's raw times. His adjusted figure already accounts for this." |
| "daily_variant -0.5, std 1.2" | "the card was inconsistent — some races ran fast, others slow. His figure from that day carries more uncertainty than usual." |
| "daily_variant +0.1, std 0.3" | "the track played true to form — normal speed, consistent card. His figure from this day is reliable." |

When the daily variant is large AND the horse ran a big figure: "His 118 came on a day the track was running almost a full point fast — but the system already adjusts for that, so the 118 is genuine. Still, the high daily variant std (1.1) means there's a touch more uncertainty than usual."

### Scenario Probabilities

Don't lead with percentages. Lead with the story, then support with probability.

| Instead of | Say something like |
|---|---|
| "P(uncontested)=0.64" | "There's only one confirmed speed type in here, so the most likely scenario is a soft lead — and that's what usually happens with a lone front-runner like this (about two-thirds of the time they get away uncontested)." |
| "P(collapse)=0.30" | "With three horses who've shown high early speed, there's a real chance — roughly one in three — that they take each other on and collapse the pace for the closers." |
| "sensitivity=0.35" | "His chances swing dramatically depending on what happens early. In a soft pace he's only about a 20% shot, but if the speed collapses he becomes a serious 35% contender. He's the definition of pace-dependent." |

### Signals

Signals should be presented as observations that tell a story, not as classified data points.

| Signal type | How to present it |
|---|---|
| hidden_ability | "He showed a PR of 128 through the first four furlongs before flattening to 116 at the wire. The raw ability is clearly there — the question is whether he can sustain it over today's longer distance. If the pace is slow enough for him to coast early, that 128-level talent might carry further." |
| pace_excuse | "Last time was a complete throw-out — the pace was nonexistent (LPD just -6) and he was stranded behind a wall of horses with nowhere to go. He ran a 109, but his best figure on a legitimate pace is 128. If the speed shows up today, he's a different horse." |
| closing_burst | "In his last start he was doing nothing at the 4f mark (PR 104 early) then exploded in the final quarter (PR 127 late), gaining 4 positions in the process. That kind of late acceleration is what you want to see from a horse whose style needs the race to come to them." |
| shape_improving | "His energy distribution has been trending the right way — in his last three starts his slope has been +1, +3, +4, compared to -2 or worse earlier in his career. He's learning to rate and finish, which suggests he's still developing." |
| style_change | "After spending his entire career pressing the pace (typically 2nd or 3rd early), his last two starts show him sitting well back (7th and 8th at the first call). The trainer has clearly changed tactics — and it's worked, with his two best late figures coming from these new positions." |
| improving_trajectory | "He's been on a steady climb — his last six figures read 101, 103, 106, 109, 112, 115. That's a horse who's improving with every start, and there's no reason to think the ceiling has been reached yet. The market may still be pricing his older, weaker form." |
| trouble_discount | "He was blocked in tight last time and had to steady at the quarter pole (trip note: 'steadied 3/8, no room'). His 104 that day is 8 points below his clean average of 112. If he gets a clean trip today, the bounce-back to his true level would make him very competitive." |

### Comparing Horses

When discussing how horses compare to each other, frame it in terms of the gap and what it means practically:

- "He holds a 10-point figure advantage over the second-best in here — that's roughly equivalent to 2 lengths at the wire if both run their figures. That's a significant edge."
- "The top four are separated by only 4 points (112, 111, 109, 108) — essentially the same horse on paper. This race will be decided by who gets the trip, not who has the most talent."
- "She's dropping from G2 company where she earned a 120 into this allowance field where the best figure is 108. On raw ability she could win this by daylight — the only question is whether there's a reason for the drop."

### Odds and Edge

When discussing market disagreements:

- "The market has him at 8/1, implying about a 12% chance. Our figures put him closer to 20% — the gap comes from his pace excuse last out and the improving trajectory the market may not have fully priced in. At 8/1 he represents genuine value."
- "She's the 2/1 favorite, and honestly the figures support it — she's the fastest horse in here by 8 points and the pace scenario favors her. No value in the win pool, but she's a strong anchor for horizontal exotics."
- "At 15/1 the market is saying he's a longshot, but our scenario model shows that in the 30% of cases where the pace collapses, he becomes a 25% chance. The question is whether you're willing to bet on that specific scenario unfolding."

## Past Performance Context

The `past_performances` module produces the full racing history for each horse in a format that mirrors a Brisnet PP but includes our PR data. Each prior start shows:

- **Running line**: position and lengths behind at every call point (Start, 2f, 4f, 6f, stretch, finish)
- **PR vector**: pr_finish, pr_early, pr_late, pr_slope for that start
- **Pace context**: the race's LPD and front_group_size (was it a speed-favoring or closer-favoring race?)
- **Daily variant**: how fast the track played that day (already baked into PR, but shown for context)
- **Trip comment**: the chart caller's one-line description of what happened ("5wd turns, brushed late")
- **Odds**: what the market thought of this horse in that race

This gives an LLM the raw evidence to reason from — not just our analytical conclusions, but the underlying data a handicapper would read.
