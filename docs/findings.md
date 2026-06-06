# Research Findings

## Finding 1: Ability is the only predictive signal (2026-06-05)

**Test:** Does running style/position/pace scenario help predict finishing position beyond ability alone?

**Result:** NO. Spearman correlation between predicted and actual finish position:
- Ability alone: r = 0.262
- Ability + style + position history: r = 0.262 (zero improvement)

**Implication:** The PR system's ability estimate IS the prediction. The pace/scenario layer adds explanation but not edge.

## Finding 2: Post position has no effect on first-call position (2026-06-05)

**Test:** What predicts where a horse ends up at the first call?

**Result:** 
- Prior position history: r = 0.503 (the dominant predictor)
- Early speed (pr_2f): r = -0.391 (secondary)
- Post position: r = 0.002 (ZERO effect)

**Implication:** For Dirt at standard distances, post position doesn't determine where horses end up. Conventional wisdom is wrong in aggregate.

## Finding 3: Market out-predicts our simple ability estimate (2026-06-06)

**Test:** If we rank horses by prior-average-PR and the market ranks by odds, who predicts the winner better?

**Result on 26,678 races (2016-2017 Dirt):**
- Horses we rate higher than market (overlays): win 5.9%
- Horses market rates higher than us (underlays): win 16.8%
- The market is 3× better at identifying winners

**Why:** Our "ability" is a simple career average on the same surface. It doesn't weight:
- Recency (how they look NOW vs career average)
- Improvement/decline trends
- Class/distance changes
- Trainer patterns
- Physical condition

**Implication:** Before competing with market odds, we need the form projection layer — recency-weighted, phase-adaptive ability estimation. The raw PR is a valid historical measurement but needs projection to be predictive.

## Finding 4: Scenario sensitivity is a mild positive signal (2026-06-05)

**Test:** Do pace-dependent horses (high scenario sensitivity) win more than pace-neutral horses?

**Result:**
- High sensitivity (>10% swing): 14.9% win rate
- Low sensitivity (<10% swing): 11.7% win rate

But when used to flag "longshots in their best scenario" — no value (1.0× random).

**Implication:** The public already prices pace dependency correctly. It's not hidden information.

## Summary: Where the Edge Lives

The edge is NOT in:
- Style classification
- Pace scenario modeling
- Position prediction

The edge IS potentially in:
- Better ability estimation than the market (requires form projection with recency/trend/phase)
- Combined with scenario context (ability edge × favorable scenario = compounding overlay)
- Market inefficiency in specific conditions (small fields, unusual pace setups, shipper horses)

The form projection system (recency-weighted, trend-aware, phase-adaptive ability estimation) is the gating requirement before the race explanation system can produce market-beating probabilities.
