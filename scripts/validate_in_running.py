"""Validate the in-running probability model at scale.

For every call point in every race in a sample:
1. Compute the in-running probability for each horse
2. Check: did the horse with the highest probability at that call actually win?
3. Calibration: when model says 40% at the 4f call, do they win ~40%?
4. How does accuracy improve as the race progresses? (should → 100% at finish)
"""
import sys
import os
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect
from src.race_explanation.in_running import build_in_running_from_race


def main():
    with connect() as conn:
        # Sample races: 2016-2017, Dirt, standard distances, 6+ runners
        races = conn.execute("""
            SELECT r.id as race_id, r.feet, r.distance_compact, r.number_of_runners
            FROM handycapper.races r
            WHERE r.breed = 'TB'
              AND EXTRACT(YEAR FROM r.date) IN (2016, 2017)
              AND r.track_condition = 'Fast'
              AND r.surface = 'Dirt'
              AND r.number_of_runners >= 6
              AND r.feet BETWEEN 3960 AND 5940
            ORDER BY random()
            LIMIT 300
        """).fetchall()

        print(f"Validating in-running model on {len(races)} races")
        print("=" * 70)

        # Collect predictions at each call fraction
        # Key: fraction_bucket → list of (predicted_prob, actually_won)
        by_fraction = defaultdict(list)
        # Top-pick accuracy at each call
        top_pick_by_fraction = defaultdict(lambda: {"correct": 0, "total": 0})
        # Brier scores by fraction
        brier_by_fraction = defaultdict(list)

        processed = 0
        skipped = 0

        for i, race in enumerate(races):
            if i % 50 == 0:
                print(f"  Processing {i}/{len(races)}...")

            try:
                probs_by_call = build_in_running_from_race(conn, race["race_id"])
            except Exception:
                skipped += 1
                continue

            if not probs_by_call:
                skipped += 1
                continue

            # Get the actual winner
            winner = conn.execute("""
                SELECT s.horse FROM handycapper.starters s
                WHERE s.race_id = %(id)s AND s.official_position = 1
            """, {"id": race["race_id"]}).fetchone()

            if not winner:
                skipped += 1
                continue

            winner_horse = winner["horse"]
            race_feet = race["feet"]

            for call_feet, probs in probs_by_call.items():
                if not probs:
                    continue

                fraction = call_feet / race_feet
                # Bucket to nearest 0.1
                frac_bucket = round(fraction * 10) / 10

                # Find the model's top pick and the winner's probability
                top_pick = max(probs, key=lambda p: p.win_probability)
                winner_prob = next((p.win_probability for p in probs if p.horse == winner_horse), 0)

                # Top pick accuracy
                top_pick_by_fraction[frac_bucket]["total"] += 1
                if top_pick.horse == winner_horse:
                    top_pick_by_fraction[frac_bucket]["correct"] += 1

                # Brier score for all horses at this call
                for p in probs:
                    actually_won = 1.0 if p.horse == winner_horse else 0.0
                    brier = (p.win_probability - actually_won) ** 2
                    brier_by_fraction[frac_bucket].append(brier)

                # Calibration: record each horse's predicted prob vs actual outcome
                for p in probs:
                    actually_won = p.horse == winner_horse
                    by_fraction[frac_bucket].append((p.win_probability, actually_won))

            processed += 1

        print(f"\n  Processed: {processed}, Skipped: {skipped}")

        # Report
        print(f"\n{'=' * 70}")
        print("  TOP-PICK ACCURACY BY RACE FRACTION")
        print("=" * 70)
        print(f"  {'Fraction':>10} {'Correct':>8} {'Total':>7} {'Rate':>7} {'vs Random':>10}")
        print(f"  {'-'*10} {'-'*8} {'-'*7} {'-'*7} {'-'*10}")

        for frac in sorted(top_pick_by_fraction.keys()):
            data = top_pick_by_fraction[frac]
            if data["total"] < 20:
                continue
            rate = data["correct"] / data["total"]
            # Estimate random baseline from field sizes
            random_rate = 1.0 / 8.5  # approximate average field size
            ratio = rate / random_rate
            print(f"  {frac:>10.1f} {data['correct']:>8} {data['total']:>7} "
                  f"{rate*100:>6.1f}% {ratio:>9.1f}×")

        print(f"\n{'=' * 70}")
        print("  BRIER SCORE BY RACE FRACTION (lower = better)")
        print("=" * 70)
        print(f"  {'Fraction':>10} {'Brier':>8} {'N':>8} {'Interpretation'}")
        print(f"  {'-'*10} {'-'*8} {'-'*8}")

        for frac in sorted(brier_by_fraction.keys()):
            scores = brier_by_fraction[frac]
            if len(scores) < 100:
                continue
            brier = np.mean(scores)
            n = len(scores)
            # Naive baseline = (1/field_size)^2 * (field_size-1) + (1-1/field_size)^2
            # ≈ 0.11 for 8 horse field
            interpretation = ""
            if brier < 0.05:
                interpretation = "Very good (near-certain)"
            elif brier < 0.08:
                interpretation = "Good"
            elif brier < 0.11:
                interpretation = "Moderate (≈ naive)"
            else:
                interpretation = "Needs improvement"
            print(f"  {frac:>10.1f} {brier:>8.4f} {n:>8} {interpretation}")

        print(f"\n{'=' * 70}")
        print("  CALIBRATION (when model says X%, do they win X%?)")
        print("=" * 70)

        # Pool all fractions, bucket by predicted probability
        all_preds = []
        for frac_data in by_fraction.values():
            all_preds.extend(frac_data)

        prob_buckets = defaultdict(lambda: {"wins": 0, "total": 0})
        for pred_prob, won in all_preds:
            bucket = round(pred_prob * 20) / 20  # bucket to nearest 5%
            prob_buckets[bucket]["total"] += 1
            if won:
                prob_buckets[bucket]["wins"] += 1

        print(f"  {'Predicted':>10} {'Actual':>8} {'N':>8} {'Calibration'}")
        print(f"  {'-'*10} {'-'*8} {'-'*8}")
        for bucket in sorted(prob_buckets.keys()):
            data = prob_buckets[bucket]
            if data["total"] < 50:
                continue
            actual_rate = data["wins"] / data["total"]
            cal = "✓" if abs(actual_rate - bucket) < 0.10 else "⚠️ miscalibrated"
            print(f"  {bucket*100:>9.0f}% {actual_rate*100:>7.1f}% {data['total']:>8} {cal}")


if __name__ == "__main__":
    main()
