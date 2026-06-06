"""Connection statistics context from racing-stats tables.

Queries the rs_* tables (point-in-time safe) to provide trainer/jockey
statistics for each starter. These are the "biographical facts" about
connections that inform the narrative — trainer win rates in specific
situations, jockey form at this track, etc.

Requires racing-stats tables to be populated:
- rs_trainer_ae_daily
- rs_jockey_career_daily
- rs_jockey_track_weekly
"""
from datetime import date, timedelta


def get_connections_context(conn, starters: list[dict], race_date, track: str) -> dict:
    """Get trainer/jockey statistics for all starters in a race.

    Args:
        conn: database connection
        starters: list of dicts with 'horse', 'jockey_first', 'jockey_last',
                  'trainer_first', 'trainer_last'
        race_date: date of the race (queries as-of the day before)
        track: track canonical code

    Returns dict keyed by horse name with connection stats.
    """
    # Query as-of yesterday (point-in-time: data <= snapshot_date)
    if isinstance(race_date, str):
        from datetime import datetime
        snapshot = (datetime.strptime(race_date, "%Y-%m-%d") - timedelta(days=1)).date()
    else:
        snapshot = race_date - timedelta(days=1)

    # Get the most recent snapshot_week_start for jockey track stats
    snapshot_week = _most_recent_monday(snapshot)

    result = {}

    for starter in starters:
        horse = starter.get("horse")
        trainer_last = starter.get("trainer_last")
        trainer_first = starter.get("trainer_first")
        jockey_last = starter.get("jockey_last")
        jockey_first = starter.get("jockey_first")

        context = {"trainer": None, "jockey": None}

        # Trainer A/E across dimensions
        if trainer_last:
            trainer_stats = _get_trainer_ae(conn, trainer_last, trainer_first, snapshot)
            if trainer_stats:
                context["trainer"] = trainer_stats

        # Jockey career + track stats
        if jockey_last:
            jockey_stats = _get_jockey_stats(conn, jockey_last, jockey_first,
                                             snapshot, snapshot_week, track)
            if jockey_stats:
                context["jockey"] = jockey_stats

        result[horse] = context

    return result


def _get_trainer_ae(conn, trainer_last: str, trainer_first: str, snapshot_date) -> dict | None:
    """Get trainer A/E statistics across all dimensions."""
    rows = conn.execute("""
        SELECT dimension, starts, wins, expected
        FROM handycapper.rs_trainer_ae_daily
        WHERE trainer_last = %(last)s AND trainer_first = %(first)s
          AND snapshot_date = %(date)s
    """, {"last": trainer_last, "first": trainer_first or "", "date": snapshot_date}).fetchall()

    if not rows:
        # Try the most recent available snapshot (might not have exact date)
        row = conn.execute("""
            SELECT snapshot_date FROM handycapper.rs_trainer_ae_daily
            WHERE trainer_last = %(last)s AND trainer_first = %(first)s
              AND snapshot_date <= %(date)s
            ORDER BY snapshot_date DESC LIMIT 1
        """, {"last": trainer_last, "first": trainer_first or "", "date": snapshot_date}).fetchone()

        if row:
            rows = conn.execute("""
                SELECT dimension, starts, wins, expected
                FROM handycapper.rs_trainer_ae_daily
                WHERE trainer_last = %(last)s AND trainer_first = %(first)s
                  AND snapshot_date = %(snap)s
            """, {"last": trainer_last, "first": trainer_first or "", "snap": row["snapshot_date"]}).fetchall()

    if not rows:
        return None

    stats = {
        "name": f"{trainer_first} {trainer_last}".strip(),
        "dimensions": {},
    }

    total_starts = 0
    total_wins = 0

    for r in rows:
        dim = r["dimension"]
        starts = r["starts"]
        wins = r["wins"]
        expected = float(r["expected"])
        ae = wins / expected if expected > 0 else 0

        stats["dimensions"][dim] = {
            "starts": starts,
            "wins": wins,
            "winPct": round(wins / starts * 100, 1) if starts > 0 else 0,
            "expected": round(expected, 1),
            "ae": round(ae, 2),  # actual/expected (1.0 = average, >1.0 = above)
        }

        total_starts += starts
        total_wins += wins

    stats["totalStarts"] = total_starts
    stats["totalWins"] = total_wins
    stats["overallWinPct"] = round(total_wins / total_starts * 100, 1) if total_starts > 0 else 0

    return stats


def _get_jockey_stats(conn, jockey_last: str, jockey_first: str,
                      snapshot_date, snapshot_week, track: str) -> dict | None:
    """Get jockey career stats + track-specific form."""
    # Career stats
    career = conn.execute("""
        SELECT career_starts, career_wins, career_win_pct
        FROM handycapper.rs_jockey_career_daily
        WHERE jockey_last = %(last)s AND jockey_first = %(first)s
          AND snapshot_date <= %(date)s
        ORDER BY snapshot_date DESC LIMIT 1
    """, {"last": jockey_last, "first": jockey_first or "", "date": snapshot_date}).fetchone()

    # Track-specific trailing 12m
    track_stats = conn.execute("""
        SELECT starts_12m, wins_12m, win_pct_12m
        FROM handycapper.rs_jockey_track_weekly
        WHERE jockey_last = %(last)s AND jockey_first = %(first)s
          AND track = %(track)s
          AND snapshot_week_start <= %(week)s
        ORDER BY snapshot_week_start DESC LIMIT 1
    """, {"last": jockey_last, "first": jockey_first or "",
          "track": track, "week": snapshot_week}).fetchone()

    if not career and not track_stats:
        return None

    stats = {
        "name": f"{jockey_first} {jockey_last}".strip(),
    }

    if career:
        stats["career"] = {
            "starts": career["career_starts"],
            "wins": career["career_wins"],
            "winPct": round(float(career["career_win_pct"]) * 100, 1),
        }

    if track_stats:
        stats["atTrack"] = {
            "starts12m": track_stats["starts_12m"],
            "wins12m": track_stats["wins_12m"],
            "winPct12m": round(float(track_stats["win_pct_12m"]) * 100, 1),
        }

    return stats


def _most_recent_monday(d) -> date:
    """Get the Monday of the week containing date d."""
    days_since_monday = d.weekday()
    return d - timedelta(days=days_since_monday)
