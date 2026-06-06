"""Past Performance (PP) formatter — aligned with chart-parser JSON schema.

Produces structured past starts in the same format chart-parser's RaceResult/Starter
uses, enriched with our PR analysis layer. This means consumers that already understand
chart-parser output can consume these PPs without learning a new schema.

Chart-parser field names/nesting:
  Starter: { horse, jockey, trainer, owner, weight, medicationEquipment, postPosition,
             officialPosition, odds, favorite, comments, pointsOfCall, fractionals, splits }
  PointOfCall: { point, text, compact, feet, relativePosition: { position, lengthsAhead, totalLengthsBehind } }
  Horse: { name, color, sex, sire: { name }, dam: { name } }
  Jockey: { firstName, lastName }
  Trainer: { firstName, lastName }

Our additions (under an "analysis" key):
  - performanceRating: { finish, early, late, slope }
  - pace: { lpd, frontGroupSize }
  - context: { dailyVariant, dailyVariantStd, tripFlags }
  - formProjection: { currentLevel, confidence, trend, trendDirection, typicalSlope }
  - signals: [{ type, strength, description }]
  - style: { class, slopeType, positionScore, versatility }
"""
from .form_projection import project_form
from .signals import detect_signals
from .running_style import classify_horse


def build_horse_pp(conn, horse: str, race_date, surface: str,
                   today_pp: int = None, today_odds: float = None,
                   max_starts: int = 10) -> dict:
    """Build past performances for a horse in chart-parser-compatible format.

    Returns a dict with:
    - "horse": chart-parser Horse object (name, sire, dam, sex, color)
    - "connections": { trainer, jockey } from most recent start
    - "record": career summary
    - "today": today's race context (pp, odds)
    - "pastStarts": list of Starter-like objects for each prior start
    - "analysis": our PR-based analytical layer
    """
    # Get identity/breeding from most recent start
    identity = conn.execute("""
        SELECT s.horse, b.sire, b.dam, b.dam_sire, b.sex, b.color,
               s.trainer_first, s.trainer_last,
               s.jockey_first, s.jockey_last, s.owner
        FROM handycapper.starters s
        LEFT JOIN handycapper.breeding b ON b.starter_id = s.id
        JOIN handycapper.races r ON r.id = s.race_id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
        ORDER BY r.date DESC LIMIT 1
    """, {"horse": horse, "date": race_date}).fetchone()

    # Career record
    record = conn.execute("""
        SELECT COUNT(*) as starts,
               COUNT(*) FILTER (WHERE s.official_position = 1) as wins,
               COUNT(*) FILTER (WHERE s.official_position <= 2) as places,
               COUNT(*) FILTER (WHERE s.official_position <= 3) as shows
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
    """, {"horse": horse, "date": race_date}).fetchone()

    # Past starts with full detail (chart-parser aligned)
    starts = conn.execute("""
        SELECT r.date as race_date, r.track_canonical, r.number as race_number,
               r.distance_compact, r.surface, r.track_condition, r.feet,
               r.number_of_runners, r.purse,
               cl.class_level,
               s.official_position, s.odds, s.pp as post_position, s.weight, s.choice,
               s.jockey_first, s.jockey_last,
               s.trainer_first, s.trainer_last,
               s.comments,
               pr.pr_finish, pr.pr_early, pr.pr_late, pr.pr_slope,
               pr.pr_2f, pr.pr_4f, pr.pr_6f, pr.pr_7f, pr.pr_1m,
               pr.lpd, pr.front_group_size, pr.biggest_gap,
               pr.positional_gain, pr.trip_flags,
               pr.daily_variant_fps, pr.daily_variant_n, pr.daily_variant_std,
               -- Points of call as JSON array (chart-parser PointOfCall format)
               (SELECT json_agg(json_build_object(
                   'point', poc.point,
                   'compact', poc.compact,
                   'feet', poc.feet,
                   'relativePosition', json_build_object(
                       'position', poc.position,
                       'totalLengthsBehind', poc.tot_len_bhd,
                       'wide', poc.wide
                   )
               ) ORDER BY poc.point)
                FROM handycapper.points_of_call poc
                WHERE poc.starter_id = s.id
               ) as points_of_call,
               -- Individual fractionals (chart-parser Fractional format)
               (SELECT json_agg(json_build_object(
                   'compact', f.compact,
                   'feet', f.feet,
                   'millis', f.millis
               ) ORDER BY f.feet)
                FROM handycapper.indiv_fractionals f
                WHERE f.starter_id = s.id AND f.millis > 0
               ) as fractionals
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
        LEFT JOIN handycapper.performance_ratings pr ON pr.starter_id = s.id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
        ORDER BY r.date DESC
        LIMIT %(limit)s
    """, {"horse": horse, "date": race_date, "limit": max_starts}).fetchall()

    # Build chart-parser-aligned past starts
    past_starts = []
    for s in starts:
        starter_obj = {
            # Chart-parser Starter fields
            "raceDate": str(s["race_date"]),
            "track": s["track_canonical"],
            "raceNumber": s["race_number"],
            "conditions": {
                "distanceCompact": s["distance_compact"],
                "surface": s["surface"],
                "trackCondition": s["track_condition"],
                "feet": s["feet"],
                "classLevel": s["class_level"],
                "purse": s["purse"],
                "numberOfRunners": s["number_of_runners"],
            },
            "officialPosition": s["official_position"],
            "postPosition": s["post_position"],
            "odds": float(s["odds"]) if s["odds"] else None,
            "choice": s["choice"],
            "jockey": {
                "firstName": s["jockey_first"],
                "lastName": s["jockey_last"],
            } if s["jockey_last"] else None,
            "trainer": {
                "firstName": s["trainer_first"],
                "lastName": s["trainer_last"],
            } if s["trainer_last"] else None,
            "weight": s["weight"],
            "comments": s["comments"],
            "pointsOfCall": s["points_of_call"],
            "fractionals": s["fractionals"],
            # Our analysis extension
            "analysis": {
                "performanceRating": {
                    "finish": _f(s["pr_finish"]),
                    "early": _f(s["pr_early"]),
                    "late": _f(s["pr_late"]),
                    "slope": _f(s["pr_slope"]),
                    "pr2f": _f(s["pr_2f"]),
                    "pr4f": _f(s["pr_4f"]),
                    "pr6f": _f(s["pr_6f"]),
                    "pr7f": _f(s["pr_7f"]),
                    "pr1m": _f(s["pr_1m"]),
                },
                "pace": {
                    "lpd": _f(s["lpd"]),
                    "frontGroupSize": s["front_group_size"],
                    "biggestGap": _f(s["biggest_gap"]),
                },
                "context": {
                    "dailyVariant": _f(s["daily_variant_fps"]),
                    "dailyVariantN": s["daily_variant_n"],
                    "dailyVariantStd": _f(s["daily_variant_std"]),
                    "tripFlags": s["trip_flags"],
                    "positionalGain": s["positional_gain"],
                },
            },
        }
        past_starts.append(starter_obj)

    # Our analytical layer for this horse
    form = project_form(conn, horse, race_date, surface)
    sigs = detect_signals(conn, horse, race_date, surface)
    style = classify_horse(conn, horse, race_date, surface)

    # Build the full output
    output = {
        # Chart-parser Horse format
        "horse": {
            "name": horse,
            "sex": identity["sex"] if identity else None,
            "color": identity["color"] if identity else None,
            "sire": {"name": identity["sire"]} if identity and identity["sire"] else None,
            "dam": {"name": identity["dam"]} if identity and identity["dam"] else None,
            "damSire": identity["dam_sire"] if identity else None,
        },
        "connections": {
            "trainer": {
                "firstName": identity["trainer_first"],
                "lastName": identity["trainer_last"],
            } if identity and identity["trainer_last"] else None,
            "jockey": {
                "firstName": identity["jockey_first"],
                "lastName": identity["jockey_last"],
            } if identity and identity["jockey_last"] else None,
            "owner": identity["owner"] if identity else None,
        },
        "today": {
            "postPosition": today_pp,
            "odds": today_odds,
        },
        "record": {
            "starts": record["starts"] if record else 0,
            "wins": record["wins"] if record else 0,
            "places": record["places"] if record else 0,
            "shows": record["shows"] if record else 0,
            "winPct": round(record["wins"] / record["starts"] * 100, 1) if record and record["starts"] > 0 else 0,
        },
        # Our analysis extension
        "analysis": {
            "formProjection": {
                "currentLevel": form.current_level,
                "confidence": form.current_level_confidence,
                "trend": form.trend,
                "trendDirection": form.trend_direction,
                "typicalSlope": form.typical_slope,
                "nStarts": form.n_starts,
                "daysSinceLast": form.days_since_last,
            } if form else None,
            "style": {
                "class": style.style_class,
                "slopeType": style.slope_type,
                "positionScore": style.position_score,
                "avgPr2f": style.avg_pr_2f,
                "versatility": style.versatility,
                "paceCorrelation": style.pace_correlation,
                "paceDifferential": style.pace_differential,
            },
            "signals": [
                {"type": s.type, "strength": round(s.strength, 2), "description": s.description}
                for s in (sigs[:5] if sigs else [])
            ],
        },
        "pastStarts": past_starts,
    }

    return output


def _f(val):
    """Convert Decimal/None to float/None."""
    return round(float(val), 1) if val is not None else None
