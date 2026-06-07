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

## Finding 5: PR advantage A/E curve — market systematically misprices dominance (2026-06-06)

**Test:** Does the market correctly price horses based on their PR advantage over the field?

**Result:** NO. A/E (actual wins / odds-implied expected wins) varies dramatically by PR advantage:

| PR Advantage | Win Rate | Market Implied | A/E |
|---|---|---|---|
| +3 | 6.3% | 16.9% | 0.37 (overbet) |
| +6 | 23.2% | 20.4% | 1.14 (fair) |
| +9 | 40.4% | 23.3% | 1.73 (underbet) |
| +12 | 53.7% | 25.7% | 2.09 (underbet) |
| +15 | 64.1% | 27.9% | 2.30 (underbet) |
| +20 | 77.5% | 31.3% | 2.48 (underbet) |

**Implication:** The market CAPS implied probability at ~30% even for massively dominant horses. A horse +15 PR above the field wins 64% but is priced at 28%. The crowd cannot believe one horse is that dominant — they spread money across alternatives.

Conversely, at +3 PR advantage (marginal favorites), the market OVERPRICES them (A/E=0.37). These are the "false favorites" that the model should fade.

**For the model:** The ability-to-edge mapping should use A/E, not raw probability comparison. A +3 horse is a FADE (market overestimates). A +12 horse is a BACK (market underestimates by 2×). This is the empirical basis for when to agree with the market vs when to disagree.

## Finding 6: Ability multiplier calibration (2026-06-06)

**Test:** What's the actual relationship between PR advantage and win rate?

**Result:** Win probability doubles every 2.7 PR points of advantage over the field average (exponential fit, R² > 0.95). The MVP used 10.0 — approximately 4× too flat.

- +5 PR: 17% win rate
- +10 PR: 46%
- +15 PR: 64%
- +20 PR: 76%

**For the model:** conditional_probs.py updated to `2.0 ** (ability_diff / 2.7)`.

## Finding 7: FTS ability default (2026-06-06)

**Test:** What PR do first-time starters achieve in their debut?

**Result:** Average PR 86.2, median 88.0 (n=115,705 TB starters 2010-2016). Overall population average is 95.5.

**For the model:** Unknown horses should default to ability_estimate=86, not 100. Using 100 treated unknowns as equivalent to proven CLM_5K runners.
