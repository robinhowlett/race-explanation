"""Validate position prediction: how well does style classification predict
where horses actually end up at the first call?

For each race:
1. Classify all starters from prior starts
2. Predict their first-call position from position_score
3. Compare to actual first-call position

Outputs:
- Correlation between predicted and actual position
- Error by style class (are E-types reliably in front?)
- Systematic biases (do we over/under-predict speed?)
- Which horses break from their expected position most often?
"""
import sys
import os
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect
from src.race_explanation.running_style import classify_horse


def main():
    with connect() as conn:
        # Large sample: 2015-2017, Dirt, standard distances
        races = conn.execute("""
            SELECT r.id as race_id, r.track_canonical, r.date, r.surface,
                   r.distance_compact, r.feet, r.number_of_runners
            FROM handycapper.races r
            WHERE r.breed = 'TB'
              AND EXTRACT(YEAR FROM r.date) BETWEEN 2015 AND 2017
              AND r.track_condition IN ('Fast', 'Firm')
              AND r.number_of_runners >= 6
              AND r.feet BETWEEN 3960 AND 7920
            ORDER BY random()
            LIMIT 500
        """).fetchall()

        print(f"Validating position prediction on {len(races)} races (2015-2017)")
        print("=" * 70)

        # Collect: (predicted_position_score, actual_position_fraction, style_class)
        all_predictions = []
        style_accuracy = defaultdict(lambda: {"correct_zone": 0, "total": 0, "errors": []})
        position_correlations = []

        for i, race in enumerate(races):
            if i % 50 == 0:
                print(f"  Processing {i}/{len(races)}...")

            # Get starters with their actual first-call positions
            starters = conn.execute("""
                SELECT s.horse, s.id as starter_id, poc.position as first_pos
                FROM handycapper.starters s
                JOIN handycapper.points_of_call poc ON poc.starter_id = s.id AND poc.point = 2
                WHERE s.race_id = %(id)s AND poc.position IS NOT NULL
                ORDER BY poc.position
            """, {"id": race["race_id"]}).fetchall()

            if len(starters) < 6:
                continue

            field_size = len(starters)
            predicted_ranks = []
            actual_ranks = []

            for s in starters:
                profile = classify_horse(conn, s["horse"], race["date"], race["surface"])
                if profile.n_starts_used == 0:
                    continue

                predicted_pos_frac = profile.position_score
                actual_pos_frac = s["first_pos"] / field_size

                predicted_ranks.append(predicted_pos_frac)
                actual_ranks.append(actual_pos_frac)

                # Record for style analysis
                all_predictions.append({
                    "predicted_frac": predicted_pos_frac,
                    "actual_frac": actual_pos_frac,
                    "style": profile.style_class,
                    "n_starts": profile.n_starts_used,
                    "versatility": profile.versatility,
                })

                # Was the style classification correct zone?
                # E should be in top 25%, EP in 25-40%, S in 40-65%, C in bottom 35%
                actual_zone = _classify_actual_zone(actual_pos_frac)
                correct = (profile.style_class == actual_zone)
                style_accuracy[profile.style_class]["total"] += 1
                if correct:
                    style_accuracy[profile.style_class]["correct_zone"] += 1
                style_accuracy[profile.style_class]["errors"].append(
                    actual_pos_frac - predicted_pos_frac
                )

            # Per-race rank correlation
            if len(predicted_ranks) >= 5:
                from scipy.stats import spearmanr
                corr, _ = spearmanr(predicted_ranks, actual_ranks)
                if not np.isnan(corr):
                    position_correlations.append(corr)

        # Report
        print(f"\n{'=' * 70}")
        print("  POSITION PREDICTION ACCURACY")
        print("=" * 70)

        print(f"\n  Per-race rank correlation (predicted vs actual position):")
        print(f"    N races: {len(position_correlations)}")
        print(f"    Mean Spearman r: {np.mean(position_correlations):.3f}")
        print(f"    Median: {np.median(position_correlations):.3f}")
        print(f"    P25-P75: {np.percentile(position_correlations, 25):.3f} to "
              f"{np.percentile(position_correlations, 75):.3f}")

        print(f"\n  Style classification zone accuracy:")
        print(f"  {'Style':<8} {'Correct':>8} {'Total':>7} {'Rate':>7} {'Mean Error':>10} {'Std':>6}")
        print(f"  {'-'*8} {'-'*8} {'-'*7} {'-'*7} {'-'*10} {'-'*6}")
        for style in ["E", "EP", "S", "C"]:
            data = style_accuracy[style]
            if data["total"] == 0:
                continue
            rate = data["correct_zone"] / data["total"]
            mean_err = np.mean(data["errors"])
            std_err = np.std(data["errors"])
            print(f"  {style:<8} {data['correct_zone']:>8} {data['total']:>7} "
                  f"{rate*100:>6.1f}% {mean_err:>+10.3f} {std_err:>6.3f}")

        # Breakdown by experience level
        print(f"\n  Accuracy by horse experience:")
        exp_buckets = defaultdict(list)
        for p in all_predictions:
            if p["n_starts"] <= 3:
                exp_buckets["1-3 starts"].append(abs(p["actual_frac"] - p["predicted_frac"]))
            elif p["n_starts"] <= 7:
                exp_buckets["4-7 starts"].append(abs(p["actual_frac"] - p["predicted_frac"]))
            else:
                exp_buckets["8+ starts"].append(abs(p["actual_frac"] - p["predicted_frac"]))

        print(f"  {'Experience':<12} {'MAE':>6} {'N':>7}")
        for bucket in ["1-3 starts", "4-7 starts", "8+ starts"]:
            errors = exp_buckets[bucket]
            if errors:
                print(f"  {bucket:<12} {np.mean(errors):>6.3f} {len(errors):>7}")

        # Versatility analysis: do versatile horses break prediction more?
        print(f"\n  Position error by versatility:")
        vers_buckets = defaultdict(list)
        for p in all_predictions:
            if p["versatility"] < 0.08:
                vers_buckets["low (<0.08)"].append(abs(p["actual_frac"] - p["predicted_frac"]))
            elif p["versatility"] < 0.15:
                vers_buckets["medium"].append(abs(p["actual_frac"] - p["predicted_frac"]))
            else:
                vers_buckets["high (>0.15)"].append(abs(p["actual_frac"] - p["predicted_frac"]))

        print(f"  {'Versatility':<14} {'MAE':>6} {'N':>7}")
        for bucket in ["low (<0.08)", "medium", "high (>0.15)"]:
            errors = vers_buckets[bucket]
            if errors:
                print(f"  {bucket:<14} {np.mean(errors):>6.3f} {len(errors):>7}")

        # The key question: when E-types DON'T lead, what happened?
        print(f"\n  E-type horses that didn't end up in front 25%:")
        e_misses = [p for p in all_predictions
                    if p["style"] == "E" and p["actual_frac"] > 0.35]
        print(f"    N: {len(e_misses)} out of {style_accuracy['E']['total']} E-types "
              f"({100*len(e_misses)/max(1,style_accuracy['E']['total']):.1f}%)")
        if e_misses:
            print(f"    Their avg actual position: {np.mean([p['actual_frac'] for p in e_misses]):.2f}")
            print(f"    Their avg versatility: {np.mean([p['versatility'] for p in e_misses]):.3f}")


def _classify_actual_zone(frac: float) -> str:
    """Map actual position fraction to style zone."""
    if frac <= 0.25:
        return "E"
    elif frac <= 0.40:
        return "EP"
    elif frac <= 0.65:
        return "S"
    else:
        return "C"


if __name__ == "__main__":
    main()
