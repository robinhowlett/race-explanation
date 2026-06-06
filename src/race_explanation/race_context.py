"""Race-level contextual base rates.

Provides expectations for this TYPE of race — what historically happens
in races with these conditions. Helps the LLM set proper expectations:
"In maiden special weight races at this distance, the favorite wins 35%
of the time and first-time starters win about 17%."
"""


def get_race_context(conn, track: str, distance_compact: str, surface: str,
                     class_level: str, field_size: int, race_date=None) -> dict:
    """Get contextual base rates for this type of race.

    Returns expectations a handicapper would know from experience:
    - Favorite win rate at this class/field size
    - How often speed holds at this distance/surface
    - First-time starter success rate (if MSW)
    - Track-specific tendencies
    """
    zone = "sprint" if _dist_feet(distance_compact) <= 4290 else "route"

    context = {}

    # Favorite win rate by class and field size
    fav_stats = conn.execute("""
        SELECT COUNT(*) as races,
               COUNT(*) FILTER (WHERE s.official_position = 1) as fav_wins
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
        WHERE s.choice = 1
          AND r.surface = %(surface)s
          AND cl.class_level = %(class)s
          AND r.number_of_runners BETWEEN %(lo)s AND %(hi)s
          AND r.track_condition IN ('Fast', 'Firm')
          AND r.date < %(race_date)s
    """, {
        "surface": surface, "class": class_level,
        "lo": max(5, field_size - 2), "hi": field_size + 2,
        "race_date": race_date,
    }).fetchone()

    if fav_stats and fav_stats["races"] >= 20:
        context["favoriteWinRate"] = round(fav_stats["fav_wins"] / fav_stats["races"], 3)
        context["favoriteN"] = fav_stats["races"]

    # Speed vs closers at this distance/surface
    pace_stats = conn.execute("""
        SELECT
            COUNT(*) FILTER (WHERE poc.position <= 2 AND s.official_position = 1) as speed_wins,
            COUNT(*) FILTER (WHERE poc.position > r.number_of_runners * 0.5 AND s.official_position = 1) as closer_wins,
            COUNT(DISTINCT r.id) as races
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        JOIN handycapper.points_of_call poc ON poc.starter_id = s.id AND poc.point = 2
        WHERE r.surface = %(surface)s
          AND r.track_condition IN ('Fast', 'Firm')
          AND r.date < %(race_date)s
          AND r.number_of_runners >= 6
          AND r.feet BETWEEN %(lo_ft)s AND %(hi_ft)s
          AND poc.position IS NOT NULL
          AND s.official_position IS NOT NULL
    """, {
        "surface": surface,
        "lo_ft": _dist_feet(distance_compact) - 330,
        "hi_ft": _dist_feet(distance_compact) + 330,
        "race_date": race_date,
    }).fetchone()

    if pace_stats and pace_stats["races"] >= 50:
        context["speedWinRate"] = round(pace_stats["speed_wins"] / pace_stats["races"], 3)
        context["closerWinRate"] = round(pace_stats["closer_wins"] / pace_stats["races"], 3)
        context["paceN"] = pace_stats["races"]

    # MSW-specific: first-time starter win rate
    if "MSW" in class_level:
        fts_stats = conn.execute("""
            SELECT COUNT(*) as starters,
                   COUNT(*) FILTER (WHERE s.official_position = 1) as wins
            FROM handycapper.starters s
            JOIN handycapper.races r ON r.id = s.race_id
            JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
            WHERE cl.class_level LIKE 'MSW%%'
              AND r.surface = %(surface)s
              AND r.track_condition IN ('Fast', 'Firm')
          AND r.date < %(race_date)s
              AND s.last_raced_date IS NULL
        """, {"surface": surface, "race_date": race_date}).fetchone()

        if fts_stats and fts_stats["starters"] >= 100:
            context["firstTimeStarterWinRate"] = round(fts_stats["wins"] / fts_stats["starters"], 3)
            context["firstTimeStarterN"] = fts_stats["starters"]

    # Track-specific: speed bias (do front-runners win more here than network average?)
    track_bias = conn.execute("""
        SELECT
            COUNT(*) FILTER (WHERE poc.position <= 2 AND s.official_position = 1) as speed_wins,
            COUNT(DISTINCT r.id) as races
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        JOIN handycapper.points_of_call poc ON poc.starter_id = s.id AND poc.point = 2
        WHERE r.track_canonical = %(track)s
          AND r.surface = %(surface)s
          AND r.track_condition IN ('Fast', 'Firm')
          AND r.date < %(race_date)s
          AND r.number_of_runners >= 6
          AND poc.position IS NOT NULL
          AND s.official_position IS NOT NULL
    """, {"track": track, "surface": surface, "race_date": race_date}).fetchone()

    if track_bias and track_bias["races"] >= 100:
        track_speed_rate = track_bias["speed_wins"] / track_bias["races"]
        # Compare to the surface-wide speed rate
        network_speed_rate = context.get("speedWinRate", 0.25)
        if track_speed_rate > network_speed_rate + 0.05:
            context["trackBias"] = "speed_favoring"
            context["trackSpeedWinRate"] = round(track_speed_rate, 3)
        elif track_speed_rate < network_speed_rate - 0.05:
            context["trackBias"] = "closer_favoring"
            context["trackSpeedWinRate"] = round(track_speed_rate, 3)
        else:
            context["trackBias"] = "neutral"

    # Winner PR distribution at this class/surface/distance
    winner_dist = conn.execute("""
        SELECT AVG(pr.pr_finish)::numeric(5,1) as avg_pr,
               STDDEV(pr.pr_finish)::numeric(5,1) as std_pr,
               PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pr.pr_finish)::numeric(5,1) as p25,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pr.pr_finish)::numeric(5,1) as median,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pr.pr_finish)::numeric(5,1) as p75,
               PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY pr.pr_finish)::numeric(5,1) as p90,
               COUNT(*) as n
        FROM handycapper.performance_ratings pr
        JOIN handycapper.starters s ON s.id = pr.starter_id
        JOIN handycapper.races r ON r.id = pr.race_id
        JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
        WHERE s.official_position = 1
          AND pr.excluded = false AND pr.pr_finish IS NOT NULL
          AND r.surface = %(surface)s
          AND r.track_condition IN ('Fast', 'Firm')
          AND r.date < %(race_date)s
          AND cl.class_level = %(class)s
          AND r.feet BETWEEN %(lo_ft)s AND %(hi_ft)s
    """, {
        "surface": surface, "class": class_level,
        "lo_ft": _dist_feet(distance_compact) - 660,
        "hi_ft": _dist_feet(distance_compact) + 660,
        "race_date": race_date,
    }).fetchone()

    if winner_dist and winner_dist["avg_pr"]:
        context["avgWinnerPR"] = float(winner_dist["avg_pr"])
        context["stdWinnerPR"] = float(winner_dist["std_pr"]) if winner_dist["std_pr"] else None
        context["winnerPRDistribution"] = {
            "p25": float(winner_dist["p25"]),
            "median": float(winner_dist["median"]),
            "p75": float(winner_dist["p75"]),
            "p90": float(winner_dist["p90"]),
            "n": winner_dist["n"],
        }

    return context


def _dist_feet(compact: str) -> int:
    mapping = {
        "2f": 1320, "4f": 2640, "4 1/2f": 2970, "5f": 3300,
        "5 1/2f": 3630, "6f": 3960, "6 1/2f": 4290, "7f": 4620,
        "7 1/2f": 4950, "1m": 5280, "1m 70y": 5490,
        "1 1/16m": 5610, "1 1/8m": 5940, "1 3/16m": 6270,
        "1 1/4m": 6600, "1 3/8m": 7260, "1 1/2m": 7920,
    }
    return mapping.get(compact, 5280)
