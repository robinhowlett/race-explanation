"""Phase A.1: Build historical lookup tables from performance_ratings data.

Produces three tables used by the MVP probability engine:
1. Win rate by position quartile × pace bucket × distance zone
2. LPD distribution by front_group_size × distance × surface
3. Lone speed bonus / contested penalty
"""
import sys
import json
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.race_explanation.db import connect


def main():
    os.makedirs("data/lookup_tables", exist_ok=True)

    with connect() as conn:
        table1 = build_win_rate_table(conn)
        table2 = build_lpd_distribution(conn)
        table3 = build_speed_bonus(conn)

    with open("data/lookup_tables/win_rates.json", "w") as f:
        json.dump(table1, f, indent=2)
    with open("data/lookup_tables/lpd_distributions.json", "w") as f:
        json.dump(table2, f, indent=2)
    with open("data/lookup_tables/speed_bonus.json", "w") as f:
        json.dump(table3, f, indent=2)

    print("Done. Lookup tables saved to data/lookup_tables/")


def build_win_rate_table(conn):
    """Win rate by position quartile × pace bucket × distance zone.

    This is the core probability lookup for the MVP:
    'Horses in the front quartile win X% when pace holds vs Y% when pace collapses.'
    """
    print("Building Table 1: Win rates by position × pace × distance...")

    rows = conn.execute("""
        WITH horse_runs AS (
            SELECT pr.starter_id, pr.race_id, pr.lpd,
                   poc.position as first_call_pos,
                   r.number_of_runners,
                   r.surface,
                   CASE WHEN r.feet <= 4290 THEN 'sprint' ELSE 'route' END as zone,
                   s.official_position
            FROM handycapper.performance_ratings pr
            JOIN handycapper.starters s ON s.id = pr.starter_id
            JOIN handycapper.races r ON r.id = pr.race_id
            JOIN handycapper.points_of_call poc ON poc.starter_id = pr.starter_id AND poc.point = 2
            WHERE pr.excluded = false AND pr.lpd IS NOT NULL
              AND poc.position IS NOT NULL AND s.official_position IS NOT NULL
              AND r.number_of_runners >= 6
              AND r.track_condition IN ('Fast', 'Firm')
        )
        SELECT
            NTILE(4) OVER (PARTITION BY race_id ORDER BY first_call_pos) as pos_quartile,
            CASE
                WHEN lpd > -20 THEN 'held'
                WHEN lpd > -35 THEN 'normal'
                ELSE 'collapse'
            END as pace_type,
            zone,
            surface,
            official_position
        FROM horse_runs
    """).fetchall()

    # Aggregate
    from collections import defaultdict
    counts = defaultdict(lambda: {"wins": 0, "top3": 0, "total": 0})

    for r in rows:
        key = f"{r['pos_quartile']}_{r['pace_type']}_{r['zone']}_{r['surface']}"
        counts[key]["total"] += 1
        if r["official_position"] == 1:
            counts[key]["wins"] += 1
        if r["official_position"] <= 3:
            counts[key]["top3"] += 1

    # Convert to rates
    table = {}
    for key, c in counts.items():
        if c["total"] >= 100:
            table[key] = {
                "win_rate": round(c["wins"] / c["total"], 4),
                "top3_rate": round(c["top3"] / c["total"], 4),
                "n": c["total"],
            }

    print(f"  {len(table)} cells with 100+ observations")
    return table


def build_lpd_distribution(conn):
    """LPD distribution by front_group_size × distance zone × surface.

    Used to calibrate scenario probabilities:
    'When 2 speed horses are in the field, LPD is typically -30 to -45.'
    """
    print("Building Table 2: LPD distributions by front group size...")

    rows = conn.execute("""
        SELECT pr.front_group_size,
               CASE WHEN r.feet <= 4290 THEN 'sprint' ELSE 'route' END as zone,
               r.surface,
               pr.lpd
        FROM handycapper.performance_ratings pr
        JOIN handycapper.races r ON r.id = pr.race_id
        WHERE pr.lpd IS NOT NULL AND pr.front_group_size IS NOT NULL
          AND pr.excluded = false
          AND r.track_condition IN ('Fast', 'Firm')
          AND r.number_of_runners >= 6
        GROUP BY pr.race_id, pr.front_group_size, r.feet, r.surface, pr.lpd
    """).fetchall()

    from collections import defaultdict
    import numpy as np

    groups = defaultdict(list)
    for r in rows:
        fg = min(r["front_group_size"], 4)  # cap at 4+
        key = f"{fg}_{r['zone']}_{r['surface']}"
        groups[key].append(float(r["lpd"]))

    table = {}
    for key, lpds in groups.items():
        if len(lpds) >= 50:
            arr = np.array(lpds)
            table[key] = {
                "p10": round(float(np.percentile(arr, 10)), 1),
                "p25": round(float(np.percentile(arr, 25)), 1),
                "median": round(float(np.median(arr)), 1),
                "p75": round(float(np.percentile(arr, 75)), 1),
                "p90": round(float(np.percentile(arr, 90)), 1),
                "mean": round(float(np.mean(arr)), 1),
                "n": len(lpds),
            }

    print(f"  {len(table)} cells with 50+ races")
    return table


def build_speed_bonus(conn):
    """Lone speed bonus / contested penalty.

    Measures: how much better do leaders perform when uncontested vs contested?
    """
    print("Building Table 3: Speed bonus/penalty by contest level...")

    rows = conn.execute("""
        SELECT pr.front_group_size, pr.pr_finish,
               CASE WHEN r.feet <= 4290 THEN 'sprint' ELSE 'route' END as zone,
               r.surface
        FROM handycapper.performance_ratings pr
        JOIN handycapper.starters s ON s.id = pr.starter_id
        JOIN handycapper.races r ON r.id = pr.race_id
        JOIN handycapper.points_of_call poc ON poc.starter_id = pr.starter_id AND poc.point = 2
        WHERE pr.excluded = false AND pr.pr_finish IS NOT NULL
          AND poc.position = 1
          AND pr.front_group_size IS NOT NULL
          AND r.track_condition IN ('Fast', 'Firm')
          AND r.number_of_runners >= 6
    """).fetchall()

    from collections import defaultdict
    import numpy as np

    groups = defaultdict(list)
    for r in rows:
        fg = "lone" if r["front_group_size"] == 1 else ("duel" if r["front_group_size"] == 2 else "pack")
        key = f"{fg}_{r['zone']}_{r['surface']}"
        groups[key].append(float(r["pr_finish"]))

    table = {}
    for key, prs in groups.items():
        if len(prs) >= 50:
            arr = np.array(prs)
            table[key] = {
                "mean_pr": round(float(np.mean(arr)), 1),
                "median_pr": round(float(np.median(arr)), 1),
                "std": round(float(np.std(arr)), 1),
                "n": len(prs),
            }

    # Compute bonuses
    print(f"  {len(table)} cells")
    for zone in ["sprint", "route"]:
        for surface in ["Dirt", "Turf"]:
            lone = table.get(f"lone_{zone}_{surface}")
            duel = table.get(f"duel_{zone}_{surface}")
            pack = table.get(f"pack_{zone}_{surface}")
            if lone and duel:
                bonus = lone["mean_pr"] - duel["mean_pr"]
                print(f"    {zone}/{surface}: lone={lone['mean_pr']:.1f} vs duel={duel['mean_pr']:.1f} "
                      f"→ bonus={bonus:+.1f} PR pts (n={lone['n']}/{duel['n']})")

    return table


if __name__ == "__main__":
    main()
