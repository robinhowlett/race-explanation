"""Explain an entire card — batch mode.

Produces one JSON file per race, or a single combined JSON for the full card.

Usage:
  python scripts/explain_card.py --track BEL --date 2015-06-06
  python scripts/explain_card.py --track BEL --date 2015-06-06 --output-dir output/
"""
import sys
import os
import argparse
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect
from src.race_explanation.models import FormEstimate, Signal as SignalModel
from src.race_explanation.running_style import classify_horse
from src.race_explanation.pace_projection import project_pace
from src.race_explanation.conditional_probs import compute_probabilities
from src.race_explanation.form_projection import project_form
from src.race_explanation.signals import detect_signals


def main():
    parser = argparse.ArgumentParser(description="Explain a full race card")
    parser.add_argument("--track", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--surface", help="Filter by surface (Dirt/Turf/Synthetic)")
    parser.add_argument("--output-dir", help="Directory to write per-race JSON files")
    parser.add_argument("--combined", action="store_true", help="Output single combined JSON")
    args = parser.parse_args()

    with connect() as conn:
        surface_filter = f"AND r.surface = '{args.surface}'" if args.surface else ""
        races = conn.execute(f"""
            SELECT r.id, r.track_canonical, r.date, r.distance_compact, r.feet,
                   r.surface, r.number_of_runners, r.number, cl.class_level
            FROM handycapper.races r
            JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
            WHERE r.track_canonical = %(track)s AND r.date = %(date)s
              AND r.final_millis > 0
              {surface_filter}
            ORDER BY r.number
        """, {"track": args.track, "date": args.date}).fetchall()

        if not races:
            print(f"No races found at {args.track} on {args.date}")
            sys.exit(1)

        print(f"Explaining {len(races)} races at {args.track} on {args.date}")

        card_output = []

        for race in races:
            print(f"  R{race['number']}: {race['distance_compact']} {race['surface']} ({race['class_level']})...", end=" ")

            explanation = _explain_one_race(conn, race)
            card_output.append(explanation)

            n_contenders = len(explanation["contenders"])
            n_signals = sum(len(c["signals"]) for c in explanation["contenders"])
            print(f"{n_contenders} contenders, {n_signals} signals")

        if args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            for exp in card_output:
                filename = f"R{exp['race']['number']}_{exp['race']['track']}_{exp['race']['date']}.json"
                with open(os.path.join(args.output_dir, filename), "w") as f:
                    json.dump(exp, f, indent=2)
            print(f"\nWritten {len(card_output)} files to {args.output_dir}/")
        elif args.combined:
            print(json.dumps({"card": card_output}, indent=2))
        else:
            # Summary view
            print(f"\n{'='*70}")
            print(f"  CARD SUMMARY: {args.track} {args.date}")
            print(f"{'='*70}")
            for exp in card_output:
                race = exp["race"]
                top = exp["contenders"][0] if exp["contenders"] else None
                scenarios = exp["scenarios"]
                most_likely = max(scenarios, key=lambda s: s["probability"]) if scenarios else None

                print(f"\n  R{race['number']} {race['distance']} {race['surface']} ({race['class']}) — {race['field_size']} runners")
                if most_likely:
                    print(f"    Pace: [{most_likely['probability']*100:.0f}%] {most_likely['description']}")
                if top:
                    form_str = f", level={top['form']['current_level']:.0f}" if top["form"] else ""
                    print(f"    Top: {top['horse']} ({top['probability']*100:.0f}%{form_str})")
                    for sig in top.get("signals", [])[:1]:
                        print(f"    Signal: {sig['description'][:70]}")

                # Market overlays
                overlays = [m for m in exp.get("market", []) if m["edge"] > 0.03]
                if overlays:
                    ov = overlays[0]
                    print(f"    Overlay: {ov['horse']} (model {ov['model_prob']*100:.0f}% vs mkt {ov['market_prob']*100:.0f}%, odds {ov['odds']:.1f})")


def _explain_one_race(conn, race) -> dict:
    """Produce structured explanation for a single race."""
    starters = conn.execute("""
        SELECT s.horse, s.pp, s.odds, s.official_position
        FROM handycapper.starters s
        WHERE s.race_id = %(id)s
        ORDER BY s.pp NULLS LAST
    """, {"id": race["id"]}).fetchall()

    # Classify + project form + detect signals
    profiles = []
    forms = {}
    horse_signals = {}

    for s in starters:
        profile = classify_horse(conn, s["horse"], race["date"], race["surface"])
        profiles.append(profile)

        proj = project_form(conn, s["horse"], race["date"], race["surface"])
        if proj:
            forms[s["horse"]] = proj
            profile.ability_estimate = proj.current_level

        sigs = detect_signals(conn, s["horse"], race["date"], race["surface"])
        if sigs:
            horse_signals[s["horse"]] = sigs[:5]

    # Pace + probabilities
    scenarios = project_pace(profiles, race["feet"], race["surface"])
    contenders = compute_probabilities(profiles, scenarios, race["feet"], race["surface"])

    # Build contender output
    contender_output = []
    for c in contenders:
        form_data = None
        if c.horse in forms:
            f = forms[c.horse]
            form_data = {
                "current_level": f.current_level,
                "confidence": f.current_level_confidence,
                "trend": f.trend,
                "trend_direction": f.trend_direction,
                "typical_slope": f.typical_slope,
                "n_starts": f.n_starts,
                "days_since_last": f.days_since_last,
            }

        signals_data = []
        if c.horse in horse_signals:
            signals_data = [
                {"type": s.type, "strength": s.strength, "description": s.description}
                for s in horse_signals[c.horse]
            ]

        contender_output.append({
            "horse": c.horse,
            "probability": c.overall_prob,
            "scenario_probs": c.scenario_probs,
            "sensitivity": c.sensitivity,
            "best_scenario": c.best_scenario,
            "worst_scenario": c.worst_scenario,
            "style": {
                "class": c.style_profile.style_class,
                "slope_type": c.style_profile.slope_type,
                "position_score": c.style_profile.position_score,
                "avg_pr_2f": c.style_profile.avg_pr_2f,
            },
            "form": form_data,
            "signals": signals_data,
        })

    # Market comparison
    market = []
    valid_odds = [s for s in starters if s["odds"] and float(s["odds"]) > 0]
    if valid_odds:
        total_implied = sum(1 / (float(s["odds"]) + 1) for s in valid_odds)
        for c in contenders:
            starter = next((s for s in valid_odds if s["horse"] == c.horse), None)
            if starter:
                implied = (1 / (float(starter["odds"]) + 1)) / total_implied
                market.append({
                    "horse": c.horse,
                    "model_prob": c.overall_prob,
                    "market_prob": round(implied, 3),
                    "edge": round(c.overall_prob - implied, 3),
                    "odds": float(starter["odds"]),
                })

    return {
        "race": {
            "id": race["id"],
            "track": race["track_canonical"],
            "date": str(race["date"]),
            "number": race["number"],
            "distance": race["distance_compact"],
            "surface": race["surface"],
            "class": race["class_level"],
            "field_size": len(starters),
        },
        "scenarios": [
            {"label": s.label, "probability": s.probability,
             "expected_lpd": s.expected_lpd, "description": s.description}
            for s in scenarios
        ],
        "contenders": contender_output,
        "market": sorted(market, key=lambda m: m["edge"], reverse=True),
        "actual_result": [
            {"position": s["official_position"], "horse": s["horse"]}
            for s in sorted(
                [s for s in starters if s["official_position"]],
                key=lambda s: s["official_position"]
            )[:3]
        ],
    }


if __name__ == "__main__":
    main()
