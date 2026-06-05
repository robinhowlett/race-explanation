"""Pre-race projection using the in-running model.

Instead of lookup tables, this projects each horse's win probability by:
1. Predicting their likely position at the first call (from style profile)
2. Computing their in-running probability from that position
3. Weighting across pace scenarios (which affect where they'll BE)

The key insight: pre-race probability = Σ P(in-running state) × P(wins | state)
"""
import numpy as np
from .models import RunningStyleProfile, PaceScenario, ContenderAnalysis
from .in_running import InRunningState, compute_in_running_probabilities


def project_race(
    profiles: list[RunningStyleProfile],
    scenarios: list[PaceScenario],
    race_feet: int,
    surface: str,
    n_simulations: int = 50,
) -> list[ContenderAnalysis]:
    """Project win probabilities using Monte Carlo simulation of in-running states.

    For each scenario, simulate multiple possible position outcomes at the
    first call (reflecting uncertainty in where each horse ends up), then
    average the in-running probabilities across simulations.
    """
    field_size = len(profiles)
    first_call_feet = _first_call_for_distance(race_feet)

    # Accumulate probabilities across simulations
    horse_scenario_probs = {p.horse: {s.label: [] for s in scenarios} for p in profiles}

    for scenario in scenarios:
        for _ in range(n_simulations):
            # Simulate positions for ALL horses with randomness
            all_states = _simulate_field_positions(
                profiles, scenario, first_call_feet, race_feet, field_size
            )

            # Compute in-running probabilities
            in_running_probs = compute_in_running_probabilities(all_states)

            # Record each horse's probability in this simulation
            for irp in in_running_probs:
                horse_scenario_probs[irp.horse][scenario.label].append(irp.win_probability)

    # Average across simulations
    contenders = []
    for profile in profiles:
        scenario_probs = {}
        for scenario in scenarios:
            sims = horse_scenario_probs[profile.horse][scenario.label]
            scenario_probs[scenario.label] = float(np.mean(sims)) if sims else 1.0 / field_size

        overall_prob = sum(
            scenario.probability * scenario_probs[scenario.label]
            for scenario in scenarios
        )

        probs_list = list(scenario_probs.values())
        sensitivity = max(probs_list) - min(probs_list) if probs_list else 0

        contenders.append(ContenderAnalysis(
            horse=profile.horse,
            overall_prob=round(overall_prob, 3),
            style_profile=profile,
            scenario_probs={k: round(v, 3) for k, v in scenario_probs.items()},
            sensitivity=round(sensitivity, 3),
            best_scenario=max(scenario_probs, key=scenario_probs.get),
            worst_scenario=min(scenario_probs, key=scenario_probs.get),
        ))

    contenders.sort(key=lambda c: c.overall_prob, reverse=True)
    return contenders


def _simulate_field_positions(
    profiles: list[RunningStyleProfile],
    scenario: PaceScenario,
    first_call_feet: int,
    race_feet: int,
    field_size: int,
) -> list[InRunningState]:
    """Simulate positions for the entire field with randomness.

    Each horse's position is drawn from a distribution centered on their
    expected position (from style profile) with noise based on their versatility.
    Positions are then ranked to ensure no ties.
    """
    # Generate raw position values (continuous, will be ranked)
    raw_positions = []
    for profile in profiles:
        # Expected position (lower = more forward)
        expected = profile.position_score * field_size

        # Scenario shifts
        if scenario.label == "uncontested" and profile.style_class == "E":
            expected = 1.0  # lone speed takes front
        elif scenario.label == "collapse" and profile.style_class in ("E", "EP"):
            expected = min(expected, 2.5)  # pressed to front
        elif scenario.label == "collapse" and profile.style_class == "C":
            expected = max(expected, field_size * 0.6)

        # Add noise: versatile horses have more position variance
        noise_std = max(0.8, profile.versatility * field_size * 0.5 + 0.5)
        noisy_pos = np.random.normal(expected, noise_std)
        raw_positions.append((profile, noisy_pos))

    # Rank to get actual positions (1 through field_size)
    raw_positions.sort(key=lambda x: x[1])

    states = []
    for rank, (profile, _) in enumerate(raw_positions, 1):
        # Estimate lengths behind from position
        lengths_per_pos = 1.5 if race_feet <= 4290 else 1.0
        if scenario.label == "collapse" and rank <= 3:
            lengths_behind = (rank - 1) * 0.5  # bunched front
        else:
            lengths_behind = (rank - 1) * lengths_per_pos

        # Add some randomness to lengths behind too
        if rank > 1:
            lengths_behind *= np.random.uniform(0.7, 1.3)

        fraction = first_call_feet / race_feet
        pace_so_far = scenario.expected_lpd * fraction

        states.append(InRunningState(
            horse=profile.horse,
            call_feet=first_call_feet,
            race_feet=race_feet,
            position=rank,
            lengths_behind=max(0, lengths_behind),
            field_size=field_size,
            pr_at_call=None,
            ability_estimate=profile.ability_estimate,
            style_class=profile.style_class,
            pace_so_far=pace_so_far,
        ))

    return states


def _simulate_first_call_state(
    profile: RunningStyleProfile,
    all_profiles: list[RunningStyleProfile],
    scenario: PaceScenario,
    first_call_feet: int,
    race_feet: int,
    field_size: int,
) -> InRunningState:
    """Simulate where a horse will likely be at the first call under a scenario.

    Position is determined by:
    - Their historical position_score (where they typically are)
    - The scenario (contested pace compresses the front, uncontested stretches it)
    - Their early speed (avg_pr_2f) relative to field
    """
    # Base position from historical style
    # position_score 0.0 = always first, 1.0 = always last
    base_position = max(1, round(profile.position_score * field_size))

    # Scenario adjustment:
    # In uncontested scenarios, the lone speed horse is further ahead
    # In collapse scenarios, the front is bunched (multiple horses pressing)
    if scenario.label == "uncontested" and profile.style_class == "E":
        # Lone leader gets extra separation
        base_position = 1
    elif scenario.label == "collapse" and profile.style_class in ("E", "EP"):
        # Speed types are bunched together at the front
        base_position = min(base_position, 3)
    elif scenario.label == "collapse" and profile.style_class == "C":
        # Closers stay back regardless
        base_position = max(base_position, int(field_size * 0.6))

    # Estimate lengths behind from position
    # Empirical: ~1.5 lengths per position at first call (sprints), ~1.0 for routes
    lengths_per_pos = 1.5 if race_feet <= 4290 else 1.0
    if scenario.label == "uncontested" and profile.style_class == "E":
        lengths_behind = 0.0
    elif scenario.label == "collapse" and base_position <= 3:
        lengths_behind = (base_position - 1) * 0.5  # bunched front
    else:
        lengths_behind = (base_position - 1) * lengths_per_pos

    # Pace context: what LPD will have developed by this call?
    # The scenario's expected_lpd is for the full race, but at the first call
    # we only have a fraction of that signal
    fraction = first_call_feet / race_feet
    pace_so_far = scenario.expected_lpd * fraction  # scale LPD by how far through

    return InRunningState(
        horse=profile.horse,
        call_feet=first_call_feet,
        race_feet=race_feet,
        position=base_position,
        lengths_behind=lengths_behind,
        field_size=field_size,
        pr_at_call=None,
        ability_estimate=profile.ability_estimate,
        style_class=profile.style_class,
        pace_so_far=pace_so_far,
    )


def _first_call_for_distance(race_feet: int) -> int:
    """Determine the first meaningful call for a given race distance.

    Use ~30-40% through the race as the first projection point.
    """
    if race_feet <= 3960:   # 6f or shorter
        return 1320  # 2f call
    elif race_feet <= 4620:  # 7f
        return 2640  # 4f call
    elif race_feet <= 5940:  # up to 1 1/8m
        return 2640  # 4f call
    else:  # routes 1 1/4m+
        return 2640  # 4f call (still early enough to shift)
