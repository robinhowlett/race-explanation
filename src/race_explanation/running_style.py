"""Running style classification from PR history.

For each horse, queries their last N rated starts and computes:
- Position preference (E/EP/S/C)
- Energy distribution (Speed/Even/Stamina)
- Ability estimate (recency-weighted pr_finish)
- Early speed capability (avg_pr_2f)
- Tactical versatility
"""
import numpy as np
from .models import RunningStyleProfile


def classify_horse(conn, horse: str, race_date, surface: str, max_starts: int = 10) -> RunningStyleProfile:
    """Classify a horse's running style from prior starts.

    Args:
        conn: database connection
        horse: horse name
        race_date: date of the race we're projecting (only uses starts BEFORE this)
        surface: 'Dirt', 'Turf', or 'Synthetic' — prefer same surface
        max_starts: maximum number of starts to use
    """
    # Query prior starts on same surface
    rows = conn.execute("""
        SELECT pr.pr_finish, pr.pr_early, pr.pr_late, pr.pr_slope, pr.pr_2f,
               pr.front_group_size, pr.lpd, pr.positional_gain,
               poc.position as first_call_pos,
               r.number_of_runners, r.date
        FROM handycapper.performance_ratings pr
        JOIN handycapper.starters s ON s.id = pr.starter_id
        JOIN handycapper.races r ON r.id = pr.race_id
        LEFT JOIN handycapper.points_of_call poc ON poc.starter_id = pr.starter_id AND poc.point = 2
        WHERE s.horse = %(horse)s
          AND r.date < %(race_date)s
          AND r.surface = %(surface)s
          AND pr.excluded = false
          AND pr.pr_finish IS NOT NULL
        ORDER BY r.date DESC
        LIMIT %(max_starts)s
    """, {"horse": horse, "race_date": race_date, "surface": surface, "max_starts": max_starts}).fetchall()

    # If insufficient same-surface starts, try all surfaces
    if len(rows) < 3:
        rows = conn.execute("""
            SELECT pr.pr_finish, pr.pr_early, pr.pr_late, pr.pr_slope, pr.pr_2f,
                   pr.front_group_size, pr.lpd, pr.positional_gain,
                   poc.position as first_call_pos,
                   r.number_of_runners, r.date
            FROM handycapper.performance_ratings pr
            JOIN handycapper.starters s ON s.id = pr.starter_id
            JOIN handycapper.races r ON r.id = pr.race_id
            LEFT JOIN handycapper.points_of_call poc ON poc.starter_id = pr.starter_id AND poc.point = 2
            WHERE s.horse = %(horse)s
              AND r.date < %(race_date)s
              AND pr.excluded = false
              AND pr.pr_finish IS NOT NULL
            ORDER BY r.date DESC
            LIMIT %(max_starts)s
        """, {"horse": horse, "race_date": race_date, "max_starts": max_starts}).fetchall()

    if not rows:
        return _unknown_profile(horse)

    n_starts = len(rows)

    # Position score: median(first_call_position / field_size)
    position_fractions = []
    for r in rows:
        if r["first_call_pos"] and r["number_of_runners"]:
            position_fractions.append(r["first_call_pos"] / r["number_of_runners"])

    if position_fractions:
        position_score = float(np.median(position_fractions))
        versatility = float(np.std(position_fractions))
    else:
        position_score = 0.5
        versatility = 0.0

    # Style class from position score
    if position_score <= 0.20:
        style_class = "E"
    elif position_score <= 0.40:
        style_class = "EP"
    elif position_score <= 0.65:
        style_class = "S"
    else:
        style_class = "C"

    # Slope type: median pr_slope
    slopes = [float(r["pr_slope"]) for r in rows if r["pr_slope"] is not None]
    median_slope = float(np.median(slopes)) if slopes else 0.0

    if median_slope < -3.0:
        slope_type = "Speed"
    elif median_slope > 3.0:
        slope_type = "Stamina"
    else:
        slope_type = "Even"

    # Ability estimate: recency-weighted pr_finish (half-life = 5 starts)
    pr_finishes = [float(r["pr_finish"]) for r in rows]
    weights = [0.5 ** (i / 5.0) for i in range(len(pr_finishes))]
    ability_estimate = float(np.average(pr_finishes, weights=weights))

    # Early speed: avg pr_2f
    pr_2f_vals = [float(r["pr_2f"]) for r in rows if r["pr_2f"] is not None]
    avg_pr_2f = float(np.mean(pr_2f_vals)) if pr_2f_vals else ability_estimate

    # Pct in front group
    in_front = sum(1 for r in rows if r["front_group_size"] and r["first_call_pos"]
                   and r["first_call_pos"] <= r["front_group_size"])
    pct_in_front_group = in_front / n_starts if n_starts > 0 else 0.0

    # Pace dependency (only if 8+ starts with LPD data)
    pace_correlation = None
    pace_differential = None
    lpd_pr_pairs = [(float(r["lpd"]), float(r["pr_finish"]))
                    for r in rows if r["lpd"] is not None and r["pr_finish"] is not None]
    if len(lpd_pr_pairs) >= 8:
        lpds = np.array([p[0] for p in lpd_pr_pairs])
        prs = np.array([p[1] for p in lpd_pr_pairs])
        if np.std(lpds) > 0 and np.std(prs) > 0:
            pace_correlation = float(np.corrcoef(lpds, prs)[0, 1])

        # Pace differential: hot pace (LPD < -30) vs mild (LPD > -20)
        hot = [pr for lpd, pr in lpd_pr_pairs if lpd < -30]
        mild = [pr for lpd, pr in lpd_pr_pairs if lpd > -20]
        if len(hot) >= 2 and len(mild) >= 2:
            pace_differential = float(np.mean(hot) - np.mean(mild))

    return RunningStyleProfile(
        horse=horse,
        style_class=style_class,
        slope_type=slope_type,
        position_score=round(position_score, 3),
        median_slope=round(median_slope, 1),
        ability_estimate=round(ability_estimate, 1),
        n_starts_used=n_starts,
        pct_in_front_group=round(pct_in_front_group, 2),
        avg_pr_2f=round(avg_pr_2f, 1),
        versatility=round(versatility, 3),
        pace_correlation=round(pace_correlation, 2) if pace_correlation is not None else None,
        pace_differential=round(pace_differential, 1) if pace_differential is not None else None,
    )


def _unknown_profile(horse: str) -> RunningStyleProfile:
    """Profile for a horse with no prior rated starts."""
    return RunningStyleProfile(
        horse=horse,
        style_class="UNKNOWN",
        slope_type="Even",
        position_score=0.5,
        median_slope=0.0,
        ability_estimate=100.0,
        n_starts_used=0,
        pct_in_front_group=0.0,
        avg_pr_2f=100.0,
        versatility=0.0,
    )
