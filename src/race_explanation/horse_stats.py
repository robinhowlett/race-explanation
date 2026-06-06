"""Per-horse biographical statistics.

Computes the record summaries a handicapper sees at the top of a PP:
- Lifetime record (starts-wins-places-shows)
- Record at today's distance
- Record at today's surface
- Record at today's track
- Current year vs prior year
- Best PR at this distance
- Days since last start
- Class of last start (stepping up? dropping?)
"""


def get_horse_stats(conn, horse: str, race_date, surface: str,
                    distance_compact: str, track: str) -> dict:
    """Compute biographical stats for a horse as of race_date.

    Returns the header-level stats that appear at the top of a Brisnet PP.
    """
    from datetime import datetime
    if isinstance(race_date, str):
        race_dt = datetime.strptime(race_date, "%Y-%m-%d").date()
    else:
        race_dt = race_date

    current_year = race_dt.year

    # All prior starts
    all_starts = conn.execute("""
        SELECT s.official_position, r.date, r.surface, r.distance_compact,
               r.track_canonical, r.feet, pr.pr_finish,
               cl.class_level
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
        LEFT JOIN handycapper.performance_ratings pr ON pr.starter_id = s.id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
        ORDER BY r.date DESC
    """, {"horse": horse, "date": race_date}).fetchall()

    if not all_starts:
        return {"lifetime": _empty_record(), "noHistory": True}

    # Lifetime
    lifetime = _compute_record(all_starts)

    # Current year
    current_year_starts = [s for s in all_starts if s["date"].year == current_year]
    current_year_record = _compute_record(current_year_starts)

    # Prior year
    prior_year_starts = [s for s in all_starts if s["date"].year == current_year - 1]
    prior_year_record = _compute_record(prior_year_starts)

    # At today's surface
    surface_starts = [s for s in all_starts if s["surface"] == surface]
    surface_record = _compute_record(surface_starts)

    # At today's distance (within 330 feet / half furlong)
    target_feet = _dist_feet(distance_compact)
    distance_starts = [s for s in all_starts
                       if s["feet"] and abs(s["feet"] - target_feet) <= 330]
    distance_record = _compute_record(distance_starts)

    # At today's track
    track_starts = [s for s in all_starts if s["track_canonical"] == track]
    track_record = _compute_record(track_starts)

    # Best PR at this distance
    distance_prs = [float(s["pr_finish"]) for s in distance_starts
                    if s["pr_finish"] is not None]
    best_pr_at_distance = max(distance_prs) if distance_prs else None

    # Best PR overall (on this surface)
    surface_prs = [float(s["pr_finish"]) for s in surface_starts
                   if s["pr_finish"] is not None]
    best_pr_surface = max(surface_prs) if surface_prs else None

    # Days since last start
    days_since_last = (race_dt - all_starts[0]["date"]).days

    # Last start class (for class movement detection)
    last_class = all_starts[0]["class_level"]

    # Class movement direction
    # (comparing last-race class to today's race class would need today's class as input)

    return {
        "lifetime": lifetime,
        "currentYear": current_year_record,
        "priorYear": prior_year_record,
        "atSurface": surface_record,
        "atDistance": distance_record,
        "atTrack": track_record,
        "bestPRAtDistance": round(best_pr_at_distance, 1) if best_pr_at_distance else None,
        "bestPROnSurface": round(best_pr_surface, 1) if best_pr_surface else None,
        "daysSinceLast": days_since_last,
        "lastClass": last_class,
        "totalStarts": len(all_starts),
    }


def _compute_record(starts: list) -> dict:
    """Compute W-P-S record from a list of starts."""
    n = len(starts)
    if n == 0:
        return _empty_record()

    wins = sum(1 for s in starts if s["official_position"] == 1)
    places = sum(1 for s in starts if s["official_position"] and s["official_position"] <= 2)
    shows = sum(1 for s in starts if s["official_position"] and s["official_position"] <= 3)

    return {
        "starts": n,
        "wins": wins,
        "places": places,
        "shows": shows,
        "winPct": round(wins / n * 100, 1) if n > 0 else 0,
        "itmPct": round(shows / n * 100, 1) if n > 0 else 0,  # in-the-money %
    }


def _empty_record() -> dict:
    return {"starts": 0, "wins": 0, "places": 0, "shows": 0, "winPct": 0, "itmPct": 0}


def _dist_feet(compact: str) -> int:
    mapping = {
        "2f": 1320, "4f": 2640, "4 1/2f": 2970, "5f": 3300,
        "5 1/2f": 3630, "6f": 3960, "6 1/2f": 4290, "7f": 4620,
        "7 1/2f": 4950, "1m": 5280, "1m 70y": 5490,
        "1 1/16m": 5610, "1 1/8m": 5940, "1 3/16m": 6270,
        "1 1/4m": 6600, "1 3/8m": 7260, "1 1/2m": 7920,
    }
    return mapping.get(compact, 5280)
