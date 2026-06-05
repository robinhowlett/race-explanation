"""Explain a race — CLI entry point.

Usage:
  python scripts/explain_race.py --race-id 298614
  python scripts/explain_race.py --track CRC --date 1996-09-28 --number 9
"""
import sys
import os
import argparse
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect
from src.race_explanation.models import RaceExplanation
from src.race_explanation.running_style import classify_horse
from src.race_explanation.pace_projection import project_pace
from src.race_explanation.conditional_probs import compute_probabilities
from src.race_explanation.narrative import generate_narrative


def main():
    parser = argparse.ArgumentParser(description="Explain a race")
    parser.add_argument("--race-id", type=int, help="Race ID from handycapper.races")
    parser.add_argument("--track", help="Track canonical code")
    parser.add_argument("--date", help="Race date (YYYY-MM-DD)")
    parser.add_argument("--number", type=int, help="Race number")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    with connect() as conn:
        # Find the race
        if args.race_id:
            race = conn.execute("""
                SELECT r.id, r.track_canonical, r.date, r.distance_compact, r.feet,
                       r.surface, r.number_of_runners, r.number, cl.class_level
                FROM handycapper.races r
                JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
                WHERE r.id = %(id)s
            """, {"id": args.race_id}).fetchone()
        elif args.track and args.date and args.number:
            race = conn.execute("""
                SELECT r.id, r.track_canonical, r.date, r.distance_compact, r.feet,
                       r.surface, r.number_of_runners, r.number, cl.class_level
                FROM handycapper.races r
                JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
                WHERE r.track_canonical = %(track)s AND r.date = %(date)s AND r.number = %(num)s
            """, {"track": args.track, "date": args.date, "num": args.number}).fetchone()
        else:
            print("Provide --race-id or --track + --date + --number")
            sys.exit(1)

        if not race:
            print("Race not found.")
            sys.exit(1)

        # Get the field
        starters = conn.execute("""
            SELECT s.horse, s.pp, s.odds, s.official_position
            FROM handycapper.starters s
            WHERE s.race_id = %(id)s
            ORDER BY s.pp
        """, {"id": race["id"]}).fetchall()

        print(f"Race: {race['track_canonical']} {race['date']} R{race['number']} "
              f"— {race['distance_compact']} {race['surface']} ({race['class_level']})")
        print(f"Field: {len(starters)} runners")
        print()

        # Step 1: Classify running styles
        print("Classifying running styles...")
        profiles = []
        for s in starters:
            profile = classify_horse(conn, s["horse"], race["date"], race["surface"])
            profiles.append(profile)

        # Step 2: Project pace scenarios
        print("Projecting pace scenarios...")
        scenarios = project_pace(profiles, race["feet"], race["surface"])

        # Step 3: Compute probabilities
        print("Computing probabilities...")
        contenders = compute_probabilities(profiles, scenarios, race["feet"], race["surface"])

        # Build explanation
        explanation = RaceExplanation(
            race_id=race["id"],
            track=race["track_canonical"],
            date=str(race["date"]),
            distance=race["distance_compact"],
            surface=race["surface"],
            field_size=len(starters),
            pace_summary=scenarios[0].description if scenarios else "",
            scenarios=scenarios,
            contenders=contenders,
        )

        # Step 4: Generate narrative
        narrative = generate_narrative(explanation)

        if args.json:
            print(json.dumps({
                "race": {"track": explanation.track, "date": explanation.date,
                         "distance": explanation.distance, "surface": explanation.surface},
                "scenarios": [{"label": s.label, "probability": s.probability,
                               "description": s.description} for s in scenarios],
                "contenders": [{"horse": c.horse, "probability": c.overall_prob,
                                "style": c.style_profile.style_class,
                                "ability": c.style_profile.ability_estimate,
                                "sensitivity": c.sensitivity,
                                "best_scenario": c.best_scenario,
                                "worst_scenario": c.worst_scenario}
                               for c in contenders[:8]],
                "narrative": narrative,
            }, indent=2))
        else:
            # Pretty print
            print()
            print("=" * 70)
            print(f"  {narrative['race_summary']}")
            print("=" * 70)
            print()
            print(f"  {narrative['pace_assessment']}")
            print()
            print("  SCENARIOS:")
            for s in scenarios:
                print(f"    [{s.probability*100:.0f}%] {s.label}: {s.description} (LPD ~{s.expected_lpd:.0f})")
            print()
            print("  CONTENDERS:")
            for i, text in enumerate(narrative["contenders"]):
                actual = starters[0]["official_position"] if starters else None
                print(f"    {i+1}. {text}")
                print()
            print(f"  {narrative['key_question']}")

            # Show actual result if available
            print()
            print("  ACTUAL RESULT:")
            finishers = sorted([s for s in starters if s["official_position"]],
                               key=lambda s: s["official_position"])
            for s in finishers[:3]:
                print(f"    #{s['official_position']}: {s['horse']}")


if __name__ == "__main__":
    main()
