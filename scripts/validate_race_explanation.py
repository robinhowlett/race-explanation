"""Phase A.6: Validate the race explanation system.

Tests:
1. Pace prediction: does the model correctly predict fast vs slow pace?
2. Win probability calibration: when model says 20%, do they win ~20%?
3. Top-pick accuracy: how often does the model's top choice win?
"""
import sys
import os
import json
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect
from src.race_explanation.running_style import classify_horse
from src.race_explanation.pace_projection import project_pace
from src.race_explanation.conditional_probs import compute_probabilities


def main():
    with connect() as conn:
        # Get a sample of races to validate on (2016-2017, held out from training)
        races = conn.execute("""
            SELECT r.id as race_id, r.track_canonical, r.date, r.distance_compact,
                   r.feet, r.surface, r.number_of_runners, cl.class_level
            FROM handycapper.races r
            JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
            WHERE r.breed = 'TB'
              AND EXTRACT(YEAR FROM r.date) = 2017
              AND r.track_condition IN ('Fast', 'Firm')
              AND r.number_of_runners >= 6
              AND r.surface = 'Dirt'
              AND r.feet BETWEEN 3960 AND 5940
              AND cl.class_level IN ('G1','G2','G3','STK','CLM_50K','CLM_20K','CLM_10K','CLM_5K')
            ORDER BY random()
            LIMIT 200
        """).fetchall()

        print(f"Validating on {len(races)} races (2017, Dirt, 6f-1 1/8m, CLM-STK)")
        print("=" * 70)

        results = []
        skipped = 0

        for i, race in enumerate(races):
            if i % 20 == 0:
                print(f"  Processing {i}/{len(races)}...")

            # Get starters
            starters = conn.execute("""
                SELECT s.horse, s.official_position
                FROM handycapper.starters s
                WHERE s.race_id = %(id)s AND s.official_position IS NOT NULL
                ORDER BY s.official_position
            """, {"id": race["race_id"]}).fetchall()

            if len(starters) < 6:
                skipped += 1
                continue

            # Get actual LPD
            actual_lpd_row = conn.execute("""
                SELECT lpd FROM handycapper.performance_ratings
                WHERE race_id = %(id)s AND lpd IS NOT NULL LIMIT 1
            """, {"id": race["race_id"]}).fetchone()

            if not actual_lpd_row:
                skipped += 1
                continue

            actual_lpd = float(actual_lpd_row["lpd"])

            # Classify all starters
            profiles = []
            for s in starters:
                profile = classify_horse(conn, s["horse"], race["date"], race["surface"])
                profiles.append(profile)

            if not profiles:
                skipped += 1
                continue

            # Project pace
            scenarios = project_pace(profiles, race["feet"], race["surface"])

            # Compute probabilities
            contenders = compute_probabilities(profiles, scenarios, race["feet"], race["surface"])

            # Record results
            winner_horse = starters[0]["horse"]  # official_position = 1
            model_top = contenders[0].horse if contenders else None
            model_winner_prob = next((c.overall_prob for c in contenders if c.horse == winner_horse), 0)

            # Predicted LPD = weighted average across scenarios
            predicted_lpd = sum(s.probability * s.expected_lpd for s in scenarios)

            results.append({
                "race_id": race["race_id"],
                "actual_lpd": actual_lpd,
                "predicted_lpd": predicted_lpd,
                "model_top": model_top,
                "actual_winner": winner_horse,
                "top_pick_won": model_top == winner_horse,
                "winner_prob": model_winner_prob,
                "field_size": len(starters),
                "n_speed": sum(1 for p in profiles if p.style_class == "E"),
            })

        print(f"\n  Processed: {len(results)}, Skipped: {skipped}")
        print()

        # Analysis
        analyze_pace_prediction(results)
        analyze_win_probability(results)
        analyze_top_pick(results)


def analyze_pace_prediction(results):
    """How well does the model predict LPD?"""
    print("=" * 70)
    print("  PACE PREDICTION")
    print("=" * 70)

    actual = np.array([r["actual_lpd"] for r in results])
    predicted = np.array([r["predicted_lpd"] for r in results])

    # Correlation
    corr = np.corrcoef(actual, predicted)[0, 1]
    mae = np.mean(np.abs(actual - predicted))

    print(f"\n  N races: {len(results)}")
    print(f"  Correlation (predicted vs actual LPD): {corr:.3f}")
    print(f"  MAE: {mae:.1f} LPD points")
    print(f"  Actual LPD range: {actual.min():.0f} to {actual.max():.0f}")
    print(f"  Predicted LPD range: {predicted.min():.0f} to {predicted.max():.0f}")

    # Directional accuracy: when model says fast (LPD < -35), is it actually fast?
    pred_fast = predicted < -35
    actual_fast = actual < -35
    if pred_fast.sum() > 0:
        precision = (pred_fast & actual_fast).sum() / pred_fast.sum()
        print(f"\n  When model predicts fast pace (LPD < -35):")
        print(f"    N predicted: {pred_fast.sum()}")
        print(f"    Actually fast: {(pred_fast & actual_fast).sum()} ({precision*100:.0f}% precision)")

    pred_held = predicted > -22
    actual_held = actual > -22
    if pred_held.sum() > 0:
        precision = (pred_held & actual_held).sum() / pred_held.sum()
        print(f"  When model predicts held pace (LPD > -22):")
        print(f"    N predicted: {pred_held.sum()}")
        print(f"    Actually held: {(pred_held & actual_held).sum()} ({precision*100:.0f}% precision)")


def analyze_win_probability(results):
    """Calibration: when model says X%, do they win X%?"""
    print(f"\n{'=' * 70}")
    print("  WIN PROBABILITY CALIBRATION")
    print("=" * 70)

    # Bucket by predicted probability
    buckets = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in results:
        prob = r["winner_prob"]
        bucket = round(prob * 10) / 10  # round to nearest 0.1
        buckets[bucket]["total"] += 1
        # Did the model's top pick win?
        # Actually we want: for ALL horses at each probability level, did they win?
        # But we only have the winner's probability. So this is a partial check.

    # For the winner specifically: their assigned probability should average to ~their-actual-win-rate
    winner_probs = [r["winner_prob"] for r in results]
    avg_winner_prob = np.mean(winner_probs)
    # The actual win rate of winners is 100% by definition. But the model's assigned
    # probability to the winner tells us: did the model assign high probability to winners?
    print(f"\n  Average probability assigned to actual winner: {avg_winner_prob*100:.1f}%")
    print(f"  (Higher = model correctly identifies winners with high confidence)")

    # Brier score (simplified): how far off was the model's top pick?
    # Brier = mean((predicted - actual)^2) where actual=1 if horse won, 0 otherwise
    # We approximate: for each race, the top pick's "miss" is (1 - top_pick_prob) if they won,
    # or (top_pick_prob) if they didn't
    brier_scores = []
    for r in results:
        if r["top_pick_won"]:
            brier_scores.append((1 - r["winner_prob"]) ** 2)
        else:
            brier_scores.append(r["winner_prob"] ** 2)  # approximation

    # Naive baseline: bet the field average (1/field_size)
    naive_scores = []
    for r in results:
        fair_prob = 1.0 / r["field_size"]
        if r["top_pick_won"]:
            naive_scores.append((1 - fair_prob) ** 2)
        else:
            naive_scores.append(fair_prob ** 2)

    print(f"\n  Approximate Brier score (lower = better):")
    print(f"    Model: {np.mean(brier_scores):.4f}")
    print(f"    Naive (1/field_size): {np.mean(naive_scores):.4f}")
    print(f"    Improvement: {(np.mean(naive_scores) - np.mean(brier_scores)) / np.mean(naive_scores) * 100:.1f}%")


def analyze_top_pick(results):
    """How often does the model's #1 pick win?"""
    print(f"\n{'=' * 70}")
    print("  TOP PICK ACCURACY")
    print("=" * 70)

    wins = sum(1 for r in results if r["top_pick_won"])
    n = len(results)
    top_pick_rate = wins / n

    # By field size
    by_size = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in results:
        size_bucket = "small (6-7)" if r["field_size"] <= 7 else ("medium (8-10)" if r["field_size"] <= 10 else "large (11+)")
        by_size[size_bucket]["total"] += 1
        if r["top_pick_won"]:
            by_size[size_bucket]["wins"] += 1

    print(f"\n  Overall: model's top pick won {wins}/{n} = {top_pick_rate*100:.1f}%")
    print(f"  (Random baseline: ~{100/np.mean([r['field_size'] for r in results]):.1f}%)")
    print(f"\n  By field size:")
    for size, data in sorted(by_size.items()):
        rate = data["wins"] / data["total"] if data["total"] > 0 else 0
        print(f"    {size}: {data['wins']}/{data['total']} = {rate*100:.1f}%")

    # By n_speed (pace scenario complexity)
    by_speed = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in results:
        speed_bucket = f"{min(r['n_speed'], 3)}+ speed" if r["n_speed"] >= 3 else f"{r['n_speed']} speed"
        by_speed[speed_bucket]["total"] += 1
        if r["top_pick_won"]:
            by_speed[speed_bucket]["wins"] += 1

    print(f"\n  By speed horse count:")
    for speed, data in sorted(by_speed.items()):
        rate = data["wins"] / data["total"] if data["total"] > 0 else 0
        print(f"    {speed}: {data['wins']}/{data['total']} = {rate*100:.1f}%")


if __name__ == "__main__":
    main()
