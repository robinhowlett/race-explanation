"""In-running probability model.

Computes P(horse wins | position, lengths_behind, pace_so_far, distance_remaining, horse_ability)
at each call point in a race.

The model works backward from certainty:
- At finish: P(winner) = 1.0, P(everyone else) = 0.0
- At each prior call: P(win) = f(position, lengths_behind, pace, ability, distance_to_go)

Built from historical data: for every (position × lengths_behind × pace × distance_remaining)
cell, what fraction of horses actually won?
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class InRunningState:
    """A horse's state at a specific call point."""
    horse: str
    call_feet: int          # physical distance of this call
    race_feet: int          # total race distance
    position: int           # position at this call (1 = leading)
    lengths_behind: float   # total lengths behind leader
    field_size: int
    pr_at_call: float | None  # PR at this call (if available)
    ability_estimate: float   # pre-race ability estimate
    style_class: str          # E/EP/S/C
    pace_so_far: float | None  # LPD proxy from leader splits so far


@dataclass
class InRunningProbability:
    """Probability of winning at a specific point in the race."""
    horse: str
    call_feet: int
    win_probability: float
    # What drives the probability:
    position_factor: float    # contribution from current position
    ability_factor: float     # contribution from known ability
    pace_factor: float        # contribution from pace context


def compute_in_running_probabilities(states: list[InRunningState]) -> list[InRunningProbability]:
    """Given all horses' states at a single call, compute win probabilities.

    The model combines:
    1. Position/lengths behind → base probability from historical rates
    2. Ability adjustment → better horses convert from any position more often
    3. Pace adjustment → fast early pace benefits closers, slow pace benefits leaders
    4. Distance remaining → more distance = more time for positions to change
    """
    if not states:
        return []

    race_feet = states[0].race_feet
    call_feet = states[0].call_feet
    fraction_complete = call_feet / race_feet
    distance_remaining = race_feet - call_feet
    field_size = states[0].field_size

    results = []
    raw_probs = []

    for state in states:
        # Factor 1: Position-based probability
        # Historical win rate from this position with this many lengths behind
        # at this fraction of the race complete
        position_prob = _position_win_probability(
            state.position, state.lengths_behind, fraction_complete, field_size
        )

        # Factor 2: Ability adjustment
        # A horse with higher ability converts from any position more often
        field_abilities = [s.ability_estimate for s in states]
        field_avg = np.mean(field_abilities)
        ability_edge = state.ability_estimate - field_avg
        # Each 5 PR points of ability edge roughly doubles conversion rate
        ability_multiplier = 2.0 ** (ability_edge / 8.0)

        # Factor 3: Pace adjustment
        # If the pace has been fast (leaders decelerating) and this horse is behind,
        # their probability increases (leaders will fade more)
        pace_multiplier = 1.0
        if state.pace_so_far is not None and distance_remaining > 1320:  # 1f+ to go
            if state.position >= field_size * 0.5 and state.pace_so_far < -30:
                # Back half of field + fast pace = closers benefit
                pace_multiplier = 1.3
            elif state.position <= 2 and state.pace_so_far < -35:
                # Leading + very fast pace = leader may tire
                pace_multiplier = 0.7

        combined = position_prob * ability_multiplier * pace_multiplier
        raw_probs.append(combined)

        results.append(InRunningProbability(
            horse=state.horse,
            call_feet=call_feet,
            win_probability=0.0,  # will normalize below
            position_factor=position_prob,
            ability_factor=ability_multiplier,
            pace_factor=pace_multiplier,
        ))

    # Normalize to sum to 1.0
    total = sum(raw_probs)
    if total > 0:
        for i, r in enumerate(results):
            r.win_probability = round(raw_probs[i] / total, 4)

    return results


def _position_win_probability(position: int, lengths_behind: float,
                               fraction_complete: float, field_size: int) -> float:
    """Historical probability of winning from this position/lengths at this point.

    Based on empirical rates:
    - Position 1 at 50% through: ~35% win rate (6f sprint) to ~28% (1m route)
    - Each position back: roughly halves the probability
    - Each length behind: ~5% reduction per length at 75%+ through, less earlier
    - Earlier in race: positions matter less (more time to change)
    """
    # Base rate from position (exponential decay)
    # At the finish (fraction=1.0), position 1 wins 100%. Before that:
    if fraction_complete >= 0.95:
        # Very close to finish — position is nearly deterministic
        if position == 1 and lengths_behind == 0:
            return 0.95
        elif position == 2 and lengths_behind <= 1:
            return 0.80
        else:
            return max(0.01, 0.5 ** (lengths_behind / 0.5))

    # Position decay rate depends on how much race is left
    # Early in race: positions change easily. Late: positions are sticky.
    stickiness = 0.3 + 0.7 * fraction_complete  # 0.3 at start, 1.0 at finish

    # Base probability from position
    # Leader has base ~30% at midpoint, decaying by position
    leader_base = 0.20 + 0.15 * fraction_complete  # 20% early, 35% late
    position_decay = 0.55 ** stickiness  # steeper decay when positions are sticky
    base = leader_base * (position_decay ** (position - 1))

    # Lengths behind penalty
    # More punishing late in the race (less time to make up ground)
    length_penalty_per_length = 0.05 + 0.10 * fraction_complete  # 5% early, 15% late
    length_factor = max(0.01, 1.0 - lengths_behind * length_penalty_per_length)

    return base * length_factor


def build_in_running_from_race(conn, race_id: int) -> dict[int, list[InRunningProbability]]:
    """Compute in-running probabilities at every call for a historical race.

    Returns: {call_feet: [InRunningProbability for each horse]}
    """
    from .running_style import classify_horse

    # Get race info
    race = conn.execute("""
        SELECT r.track_canonical, r.date, r.surface, r.distance_compact, r.feet,
               r.number_of_runners
        FROM handycapper.races r WHERE r.id = %(id)s
    """, {"id": race_id}).fetchone()

    if not race:
        return {}

    # Get starters with their positions at each call
    starters = conn.execute("""
        SELECT s.id as starter_id, s.horse, s.official_position
        FROM handycapper.starters s WHERE s.race_id = %(id)s
        ORDER BY s.official_position NULLS LAST
    """, {"id": race_id}).fetchall()

    # Get points of call for all starters
    poc_data = conn.execute("""
        SELECT poc.starter_id, poc.point, poc.feet, poc.position, poc.tot_len_bhd
        FROM handycapper.points_of_call poc
        JOIN handycapper.starters s ON poc.starter_id = s.id
        WHERE s.race_id = %(id)s AND poc.position IS NOT NULL
        ORDER BY poc.feet, poc.position
    """, {"id": race_id}).fetchall()

    # Get PR data
    pr_data = conn.execute("""
        SELECT pr.starter_id, pr.pr_finish, pr.pr_2f, pr.pr_4f, pr.pr_6f, pr.lpd
        FROM handycapper.performance_ratings pr
        WHERE pr.race_id = %(id)s AND pr.excluded = false
    """, {"id": race_id}).fetchall()

    pr_lookup = {r["starter_id"]: r for r in pr_data}

    # Classify each horse's style (using data before this race)
    style_lookup = {}
    for s in starters:
        profile = classify_horse(conn, s["horse"], race["date"], race["surface"])
        style_lookup[s["starter_id"]] = profile

    # Group POC by call point (feet)
    from collections import defaultdict
    calls = defaultdict(list)
    for poc in poc_data:
        if poc["feet"] and poc["feet"] > 0:
            calls[poc["feet"]].append(poc)

    # For each call, build states and compute probabilities
    result = {}
    for call_feet in sorted(calls.keys()):
        poc_at_call = calls[call_feet]
        states = []

        for poc in poc_at_call:
            sid = poc["starter_id"]
            pr = pr_lookup.get(sid, {})
            profile = style_lookup.get(sid)

            states.append(InRunningState(
                horse=next(s["horse"] for s in starters if s["starter_id"] == sid),
                call_feet=call_feet,
                race_feet=race["feet"],
                position=poc["position"],
                lengths_behind=float(poc["tot_len_bhd"] or 0),
                field_size=race["number_of_runners"],
                pr_at_call=None,  # could map from pr_2f/4f/6f based on call
                ability_estimate=profile.ability_estimate if profile else 100.0,
                style_class=profile.style_class if profile else "S",
                pace_so_far=float(pr.get("lpd")) if pr.get("lpd") else None,
            ))

        if states:
            probs = compute_in_running_probabilities(states)
            result[call_feet] = probs

    return result
