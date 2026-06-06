"""Form projection: recency-weighted, trend-aware ability estimation.

Takes a horse's PR history and produces a current ability estimate that's
competitive with the market. Key differences from simple career average:

1. Recency: half-life of 5 starts (recent races count 2× more than 10 starts ago)
2. Trend: detects improving/declining form and extrapolates slightly
3. Confidence: tighter when consistent, wider when erratic or after layoff
4. Trip discount: troubled races contribute less to the estimate
5. Surface-specific: dirt and turf are separate projections
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class FormProjection:
    horse: str
    surface: str
    snapshot_date: str

    # Core ability
    current_level: float          # recency-weighted pr_finish
    current_level_confidence: float  # 0-1 (1 = very confident)

    # Shape
    typical_slope: float          # weighted avg of pr_slope
    current_early: float          # recency-weighted pr_early
    current_late: float           # recency-weighted pr_late

    # Trend
    trend: float                  # recent - older (positive = improving)
    trend_direction: str          # 'improving', 'stable', 'declining'

    # Context
    n_starts: int
    days_since_last: int
    last_pr_finish: float | None


def project_form(conn, horse: str, race_date, surface: str) -> FormProjection | None:
    """Compute a form projection for a horse at a point in time.

    Uses ONLY starts before race_date on the specified surface.
    Falls back to all surfaces if insufficient same-surface data.
    """
    rows = _get_prior_starts(conn, horse, race_date, surface)

    if not rows:
        # Try all surfaces
        rows = _get_prior_starts(conn, horse, race_date, surface=None)

    if not rows:
        return None

    n_starts = len(rows)

    # Compute days since last start
    from datetime import datetime
    race_dt = datetime.strptime(str(race_date), "%Y-%m-%d") if isinstance(race_date, str) else race_date
    last_race_dt = rows[0]["date"]
    if hasattr(last_race_dt, 'strftime'):
        days_since = (race_dt.date() - last_race_dt).days if hasattr(race_dt, 'date') else (race_dt - last_race_dt).days
    else:
        days_since = 999

    # Recency weights: half-life of 5 starts
    half_life = 5.0
    weights = np.array([0.5 ** (i / half_life) for i in range(n_starts)])

    # Trip discount: troubled races get reduced weight
    for i, r in enumerate(rows):
        flags = r.get("trip_flags") or ""
        if "steadied" in flags or "blocked" in flags or "checked" in flags:
            weights[i] *= 0.7
        elif "bumped" in flags:
            weights[i] *= 0.85

    # Normalize weights
    weight_sum = weights.sum()
    if weight_sum == 0:
        return None
    norm_weights = weights / weight_sum

    # Current level: weighted average of pr_finish
    finishes = np.array([float(r["pr_finish"]) for r in rows])
    current_level = float(np.dot(finishes, norm_weights))

    # Shape: weighted average of slope, early, late
    slopes = np.array([float(r["pr_slope"]) if r["pr_slope"] is not None else 0.0 for r in rows])
    typical_slope = float(np.dot(slopes, norm_weights))

    earlies = np.array([float(r["pr_early"]) if r["pr_early"] is not None else current_level for r in rows])
    lates = np.array([float(r["pr_late"]) if r["pr_late"] is not None else current_level for r in rows])
    current_early = float(np.dot(earlies, norm_weights))
    current_late = float(np.dot(lates, norm_weights))

    # Trend: compare recent (last 3) vs older (4-8)
    if n_starts >= 5:
        recent_avg = float(np.mean(finishes[:3]))
        older_avg = float(np.mean(finishes[3:min(8, n_starts)]))
        trend = recent_avg - older_avg
    elif n_starts >= 3:
        recent_avg = float(np.mean(finishes[:2]))
        older_avg = float(np.mean(finishes[2:]))
        trend = recent_avg - older_avg
    else:
        trend = 0.0

    if trend > 3:
        trend_direction = "improving"
    elif trend < -3:
        trend_direction = "declining"
    else:
        trend_direction = "stable"

    # Confidence: from consistency + recency + sample size
    weighted_std = float(np.sqrt(np.dot((finishes - current_level) ** 2, norm_weights)))
    # Confidence decreases with:
    # - high std (erratic form)
    # - few starts (limited data)
    # - long layoff (stale data)
    consistency_factor = max(0.3, 1.0 - weighted_std / 20.0)  # std of 20 → confidence 0.3
    sample_factor = min(1.0, n_starts / 8.0)  # 8+ starts → full confidence from sample
    freshness_factor = max(0.5, 1.0 - days_since / 180.0)  # 180+ days → half confidence

    confidence = consistency_factor * sample_factor * freshness_factor
    confidence = max(0.1, min(1.0, confidence))

    return FormProjection(
        horse=horse,
        surface=surface,
        snapshot_date=str(race_date),
        current_level=round(current_level, 1),
        current_level_confidence=round(confidence, 2),
        typical_slope=round(typical_slope, 1),
        current_early=round(current_early, 1),
        current_late=round(current_late, 1),
        trend=round(trend, 1),
        trend_direction=trend_direction,
        n_starts=n_starts,
        days_since_last=days_since,
        last_pr_finish=round(float(rows[0]["pr_finish"]), 1) if rows else None,
    )


def _get_prior_starts(conn, horse: str, race_date, surface: str | None, limit: int = 15):
    """Query prior rated starts for a horse."""
    surface_filter = "AND r.surface = %(surface)s" if surface else ""

    return conn.execute(f"""
        SELECT pr.pr_finish, pr.pr_early, pr.pr_late, pr.pr_slope,
               pr.trip_flags, pr.daily_variant_fps, pr.daily_variant_std,
               pr.lpd, pr.positional_gain,
               r.date, r.distance_compact, r.number_of_runners,
               s.official_position
        FROM handycapper.performance_ratings pr
        JOIN handycapper.starters s ON s.id = pr.starter_id
        JOIN handycapper.races r ON r.id = pr.race_id
        WHERE s.horse = %(horse)s
          AND r.date < %(date)s
          AND pr.excluded = false
          AND pr.pr_finish IS NOT NULL
          {surface_filter}
        ORDER BY r.date DESC
        LIMIT %(limit)s
    """, {"horse": horse, "date": race_date, "surface": surface, "limit": limit}).fetchall()
