"""Past Performance (PP) formatter.

Produces a structured representation of each horse's recent racing history
in a format familiar to handicappers, enriched with PR system data.

The output gives an LLM everything a handicapper would see in a Brisnet PP,
plus our analytical layer (PRs, signals, form projection).
"""
from dataclasses import dataclass, field
from .form_projection import project_form
from .signals import detect_signals


@dataclass
class PastPerformanceLine:
    """One prior start — a single line in the PP."""
    # Race info
    date: str
    track: str
    distance: str
    surface: str
    condition: str
    class_level: str
    purse: int | None
    field_size: int

    # Horse's performance
    finish_position: int | None
    beaten_lengths: float | None      # total lengths behind winner at finish
    odds: float | None
    post_position: int | None
    jockey: str | None
    weight: int | None

    # Running line (position at each call with lengths behind)
    running_line: list[dict] | None   # [{call, position, lengths_behind}]

    # Speed/PR data
    pr_finish: float | None
    pr_early: float | None
    pr_late: float | None
    pr_slope: float | None

    # Pace context
    lpd: float | None
    front_group_size: int | None

    # Trip/context
    trip_flags: str | None
    daily_variant: float | None
    daily_variant_std: float | None

    # Comment (from starters.comments — the trip note)
    comment: str | None


@dataclass
class HorsePP:
    """Full past performances for one horse entering a race."""
    # Identity
    horse: str
    age: int | None
    sex: str | None
    sire: str | None
    dam: str | None
    owner: str | None
    trainer: str | None
    jockey: str | None   # today's jockey

    # Today's race context
    post_position: int | None
    morning_line_odds: float | None

    # Record summary
    starts: int
    wins: int
    places: int
    shows: int
    earnings: int | None

    # Our analytical layer
    form_level: float | None          # current recency-weighted ability
    form_confidence: float | None
    form_trend: str | None            # improving/stable/declining
    style_class: str | None           # E/EP/S/C
    slope_type: str | None            # Speed/Even/Stamina
    signals: list[dict] = field(default_factory=list)

    # Past starts (most recent first)
    starts_history: list[PastPerformanceLine] = field(default_factory=list)


def build_horse_pp(conn, horse: str, race_date, surface: str,
                   today_track: str = None, today_pp: int = None,
                   today_jockey: str = None, today_odds: float = None,
                   max_starts: int = 10) -> HorsePP:
    """Build full past performances for a horse.

    Combines chartbase data with our PR analysis.
    """
    # Get horse identity/breeding
    identity = conn.execute("""
        SELECT DISTINCT ON (s.horse)
               s.horse, b.sire, b.dam, b.sex,
               s.trainer_first || ' ' || s.trainer_last as trainer,
               s.jockey_first || ' ' || s.jockey_last as jockey
        FROM handycapper.starters s
        LEFT JOIN handycapper.breeding b ON b.starter_id = s.id
        JOIN handycapper.races r ON r.id = s.race_id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
        ORDER BY s.horse, r.date DESC
    """, {"horse": horse, "date": race_date}).fetchone()

    # Get career record
    record = conn.execute("""
        SELECT COUNT(*) as starts,
               COUNT(*) FILTER (WHERE s.official_position = 1) as wins,
               COUNT(*) FILTER (WHERE s.official_position <= 2) as places,
               COUNT(*) FILTER (WHERE s.official_position <= 3) as shows
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
    """, {"horse": horse, "date": race_date}).fetchone()

    # Get recent starts with full detail
    starts = conn.execute("""
        SELECT r.date, r.track_canonical, r.distance_compact, r.surface,
               r.track_condition, r.number_of_runners, r.purse,
               cl.class_level,
               s.official_position, s.odds, s.pp,
               s.jockey_first || ' ' || s.jockey_last as jockey, s.weight,
               s.comments,
               pr.pr_finish, pr.pr_early, pr.pr_late, pr.pr_slope,
               pr.lpd, pr.front_group_size, pr.trip_flags,
               pr.daily_variant_fps, pr.daily_variant_std,
               -- Running line from points of call
               (SELECT json_agg(json_build_object(
                   'call', poc.compact, 'position', poc.position,
                   'lengths_behind', poc.tot_len_bhd
               ) ORDER BY poc.point)
                FROM handycapper.points_of_call poc
                WHERE poc.starter_id = s.id AND poc.position IS NOT NULL
               ) as running_line,
               -- Beaten lengths at finish
               (SELECT poc.tot_len_bhd
                FROM handycapper.points_of_call poc
                WHERE poc.starter_id = s.id
                  AND poc.point = (SELECT MAX(p2.point) FROM handycapper.points_of_call p2 WHERE p2.starter_id = s.id)
               ) as beaten_lengths
        FROM handycapper.starters s
        JOIN handycapper.races r ON r.id = s.race_id
        JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
        LEFT JOIN handycapper.performance_ratings pr ON pr.starter_id = s.id
        WHERE s.horse = %(horse)s AND r.date < %(date)s
        ORDER BY r.date DESC
        LIMIT %(limit)s
    """, {"horse": horse, "date": race_date, "limit": max_starts}).fetchall()

    # Build PP lines
    pp_lines = []
    for s in starts:
        running_line = None
        if s["running_line"]:
            running_line = s["running_line"]

        pp_lines.append(PastPerformanceLine(
            date=str(s["date"]),
            track=s["track_canonical"],
            distance=s["distance_compact"],
            surface=s["surface"],
            condition=s["track_condition"] or "Fast",
            class_level=s["class_level"],
            purse=s["purse"],
            field_size=s["number_of_runners"],
            finish_position=s["official_position"],
            beaten_lengths=float(s["beaten_lengths"]) if s["beaten_lengths"] else None,
            odds=float(s["odds"]) if s["odds"] else None,
            post_position=s["pp"],
            jockey=s["jockey"],
            weight=s["weight"],
            running_line=running_line,
            pr_finish=float(s["pr_finish"]) if s["pr_finish"] else None,
            pr_early=float(s["pr_early"]) if s["pr_early"] else None,
            pr_late=float(s["pr_late"]) if s["pr_late"] else None,
            pr_slope=float(s["pr_slope"]) if s["pr_slope"] else None,
            lpd=float(s["lpd"]) if s["lpd"] else None,
            front_group_size=s["front_group_size"],
            trip_flags=s["trip_flags"],
            daily_variant=float(s["daily_variant_fps"]) if s["daily_variant_fps"] else None,
            daily_variant_std=float(s["daily_variant_std"]) if s["daily_variant_std"] else None,
            comment=s["comments"],
        ))

    # Get our analytical layer
    form = project_form(conn, horse, race_date, surface)
    sigs = detect_signals(conn, horse, race_date, surface)

    from .running_style import classify_horse
    style = classify_horse(conn, horse, race_date, surface)

    return HorsePP(
        horse=horse,
        age=None,  # not easily available without date-of-birth
        sex=None,
        sire=identity["sire"] if identity else None,
        dam=identity["dam"] if identity else None,
        owner=None,
        trainer=identity["trainer"] if identity else None,
        jockey=today_jockey,
        post_position=today_pp,
        morning_line_odds=today_odds,
        starts=record["starts"] if record else 0,
        wins=record["wins"] if record else 0,
        places=record["places"] if record else 0,
        shows=record["shows"] if record else 0,
        earnings=None,
        form_level=form.current_level if form else None,
        form_confidence=form.current_level_confidence if form else None,
        form_trend=form.trend_direction if form else None,
        style_class=style.style_class,
        slope_type=style.slope_type,
        signals=[{"type": s.type, "strength": s.strength, "description": s.description}
                 for s in (sigs[:5] if sigs else [])],
        starts_history=pp_lines,
    )


def pp_to_dict(pp: HorsePP) -> dict:
    """Convert a HorsePP to a JSON-serializable dict."""
    return {
        "horse": pp.horse,
        "breeding": {"sire": pp.sire, "dam": pp.dam},
        "connections": {"trainer": pp.trainer, "jockey": pp.jockey},
        "today": {
            "post_position": pp.post_position,
            "morning_line": pp.morning_line_odds,
        },
        "record": {
            "starts": pp.starts, "wins": pp.wins,
            "places": pp.places, "shows": pp.shows,
            "win_pct": round(pp.wins / pp.starts * 100, 1) if pp.starts > 0 else 0,
        },
        "analysis": {
            "form_level": pp.form_level,
            "form_confidence": pp.form_confidence,
            "form_trend": pp.form_trend,
            "style": pp.style_class,
            "slope_type": pp.slope_type,
            "signals": pp.signals,
        },
        "past_starts": [
            {
                "date": line.date,
                "track": line.track,
                "distance": line.distance,
                "surface": line.surface,
                "condition": line.condition,
                "class": line.class_level,
                "field_size": line.field_size,
                "finish": line.finish_position,
                "beaten_lengths": line.beaten_lengths,
                "odds": line.odds,
                "pp": line.post_position,
                "jockey": line.jockey,
                "running_line": line.running_line,
                "pr": {
                    "finish": line.pr_finish,
                    "early": line.pr_early,
                    "late": line.pr_late,
                    "slope": line.pr_slope,
                },
                "pace": {
                    "lpd": line.lpd,
                    "front_group": line.front_group_size,
                },
                "context": {
                    "daily_variant": line.daily_variant,
                    "daily_variant_std": line.daily_variant_std,
                    "trip_flags": line.trip_flags,
                    "comment": line.comment,
                },
            }
            for line in pp.starts_history
        ],
    }
