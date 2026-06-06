"""Explain a race — v2 with form projection + signals + structured JSON.

Produces the structured output an LLM would consume to generate narratives.

Usage:
  python scripts/explain_race_v2.py --track BEL --date 2015-06-06 --number 11
  python scripts/explain_race_v2.py --race-id 298614 --json
"""
import sys
import os
import argparse
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect
from src.race_explanation.models import RaceExplanation, FormEstimate, Signal as SignalModel
from src.race_explanation.running_style import classify_horse
from src.race_explanation.pace_projection import project_pace
from src.race_explanation.conditional_probs import compute_probabilities
from src.race_explanation.form_projection import project_form
from src.race_explanation.signals import detect_signals


def main():
    parser = argparse.ArgumentParser(description="Explain a race (v2)")
    parser.add_argument("--race-id", type=int)
    parser.add_argument("--track")
    parser.add_argument("--date")
    parser.add_argument("--number", type=int)
    parser.add_argument("--json", action="store_true", help="Output structured JSON")
    args = parser.parse_args()

    with connect() as conn:
        race = _find_race(conn, args)
        if not race:
            print("Race not found.")
            sys.exit(1)

        starters = conn.execute("""
            SELECT s.horse, s.pp, s.odds, s.official_position
            FROM handycapper.starters s
            WHERE s.race_id = %(id)s
            ORDER BY s.pp NULLS LAST
        """, {"id": race["id"]}).fetchall()

        # Step 1: Classify styles
        profiles = []
        for s in starters:
            profile = classify_horse(conn, s["horse"], race["date"], race["surface"])
            profiles.append(profile)

        # Step 2: Form projections
        forms = {}
        for s in starters:
            proj = project_form(conn, s["horse"], race["date"], race["surface"])
            if proj:
                forms[s["horse"]] = proj

        # Step 3: Detect signals for each horse
        horse_signals = {}
        for s in starters:
            sigs = detect_signals(conn, s["horse"], race["date"], race["surface"])
            if sigs:
                horse_signals[s["horse"]] = sigs[:5]  # top 5 signals

        # Step 4: Project pace
        scenarios = project_pace(profiles, race["feet"], race["surface"])

        # Step 5: Compute probabilities (using form projection for ability)
        # Override ability_estimate with form projection's current_level
        for profile in profiles:
            if profile.horse in forms:
                profile.ability_estimate = forms[profile.horse].current_level

        contenders = compute_probabilities(profiles, scenarios, race["feet"], race["surface"])

        # Step 6: Attach form and signals to contenders
        for c in contenders:
            if c.horse in forms:
                f = forms[c.horse]
                c.form = FormEstimate(
                    current_level=f.current_level,
                    confidence=f.current_level_confidence,
                    trend=f.trend,
                    trend_direction=f.trend_direction,
                    typical_slope=f.typical_slope,
                    n_starts=f.n_starts,
                    days_since_last=f.days_since_last,
                )
            if c.horse in horse_signals:
                c.signals = [
                    SignalModel(type=s.type, strength=s.strength,
                               description=s.description, evidence=s.evidence)
                    for s in horse_signals[c.horse]
                ]

        # Step 7: Market context (if odds available)
        market = []
        total_implied = sum(1/(float(s["odds"])+1) for s in starters if s["odds"] and float(s["odds"]) > 0)
        for c in contenders:
            starter = next((s for s in starters if s["horse"] == c.horse), None)
            if starter and starter["odds"] and float(starter["odds"]) > 0:
                implied = (1 / (float(starter["odds"]) + 1)) / total_implied  # normalized
                edge = c.overall_prob - implied
                market.append({
                    "horse": c.horse,
                    "model_prob": c.overall_prob,
                    "market_prob": round(implied, 3),
                    "edge": round(edge, 3),
                    "odds": float(starter["odds"]),
                })

        # Build output
        output = {
            # Chart-parser RaceResult fields
            "raceDate": str(race["date"]),
            "track": {"code": race["track_canonical"]},
            "raceNumber": race["number"],
            "distanceSurfaceTrackRecord": {
                "distance": {"compact": race["distance_compact"], "feet": race["feet"]},
                "surface": race["surface"],
            },
            "conditions": {
                "classLevel": race["class_level"],
            },
            "numberOfRunners": len(starters),
            # Our analysis extension
            "analysis": {
            "scenarios": [
                {"label": s.label, "probability": s.probability,
                 "expected_lpd": s.expected_lpd, "description": s.description}
                for s in scenarios
            ],
            "contenders": [
                {
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
                        "versatility": c.style_profile.versatility,
                    },
                    "form": {
                        "current_level": c.form.current_level,
                        "confidence": c.form.confidence,
                        "trend": c.form.trend,
                        "trend_direction": c.form.trend_direction,
                        "typical_slope": c.form.typical_slope,
                        "n_starts": c.form.n_starts,
                        "days_since_last": c.form.days_since_last,
                    } if c.form else None,
                    "signals": [
                        {"type": s.type, "strength": s.strength, "description": s.description}
                        for s in c.signals
                    ] if c.signals else [],
                }
                for c in contenders
            ],
            "market": sorted(market, key=lambda m: m["edge"], reverse=True) if market else [],
            },  # end analysis
            "actualResult": [
                {"officialPosition": s["official_position"], "horse": s["horse"]}
                for s in sorted(
                    [s for s in starters if s["official_position"]],
                    key=lambda s: s["official_position"]
                )[:3]
            ],
        }

        if args.json:
            print(json.dumps(output, indent=2))
        else:
            _pretty_print(output)


def _find_race(conn, args):
    if args.race_id:
        return conn.execute("""
            SELECT r.id, r.track_canonical, r.date, r.distance_compact, r.feet,
                   r.surface, r.number_of_runners, r.number, cl.class_level
            FROM handycapper.races r
            JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
            WHERE r.id = %(id)s
        """, {"id": args.race_id}).fetchone()
    elif args.track and args.date and args.number:
        return conn.execute("""
            SELECT r.id, r.track_canonical, r.date, r.distance_compact, r.feet,
                   r.surface, r.number_of_runners, r.number, cl.class_level
            FROM handycapper.races r
            JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
            WHERE r.track_canonical = %(t)s AND r.date = %(d)s AND r.number = %(n)s
        """, {"t": args.track, "d": args.date, "n": args.number}).fetchone()
    return None


def _pretty_print(output):
    dist = output["distanceSurfaceTrackRecord"]
    print(f'\n{output["numberOfRunners"]}-horse field at {output["track"]["code"]} {output["raceDate"]} R{output["raceNumber"]}')
    print(f'{dist["distance"]["compact"]} {dist["surface"]} ({output["conditions"]["classLevel"]})')
    print("=" * 70)

    analysis = output["analysis"]
    print(f'\nSCENARIOS:')
    for s in analysis["scenarios"]:
        print(f'  [{s["probability"]*100:.0f}%] {s["description"]}')

    print(f'\nCONTENDERS:')
    for c in analysis["contenders"][:6]:
        form_str = ""
        if c["form"]:
            form_str = f' (level={c["form"]["current_level"]:.0f}, {c["form"]["trend_direction"]}, conf={c["form"]["confidence"]:.2f})'
        print(f'\n  {c["horse"]} — {c["probability"]*100:.0f}%{form_str}')
        print(f'    Style: {c["style"]["class"]} ({c["style"]["slope_type"]})')
        if c["sensitivity"] > 0.03:
            print(f'    Range: {min(c["scenario_probs"].values())*100:.0f}%-{max(c["scenario_probs"].values())*100:.0f}% across scenarios')
        for sig in c["signals"][:2]:
            print(f'    Signal [{sig["strength"]:.1f}]: {sig["description"]}')

    if analysis["market"]:
        overlays = [m for m in analysis["market"] if m["edge"] > 0.03]
        if overlays:
            print(f'\nMARKET DISAGREEMENTS (model > market):')
            for m in overlays[:3]:
                print(f'  {m["horse"]}: model {m["model_prob"]*100:.0f}% vs market {m["market_prob"]*100:.0f}% '
                      f'(edge +{m["edge"]*100:.0f}%, odds {m["odds"]:.1f})')

    print(f'\nACTUAL RESULT:')
    for r in output["actualResult"]:
        print(f'  #{r["officialPosition"]}: {r["horse"]}')


if __name__ == "__main__":
    main()
