"""Scenario-conditional win probabilities.

For each horse under each scenario, compute their probability of winning.
MVP uses lookup tables; Phase B will add calibrated softmax.
"""
import json
import os
from .models import RunningStyleProfile, PaceScenario, ContenderAnalysis


def compute_probabilities(
    profiles: list[RunningStyleProfile],
    scenarios: list[PaceScenario],
    distance_feet: int,
    surface: str,
) -> list[ContenderAnalysis]:
    """Compute scenario-conditional and overall win probabilities."""

    zone = "sprint" if distance_feet <= 4290 else "route"
    win_rates = _load_win_rates()

    # Field average ability (for relative scaling)
    abilities = [p.ability_estimate for p in profiles if p.style_class != "UNKNOWN"]
    field_avg = sum(abilities) / len(abilities) if abilities else 100.0

    contenders = []
    for profile in profiles:
        scenario_probs = {}

        for scenario in scenarios:
            # Map scenario to pace bucket
            pace_bucket = _lpd_to_bucket(scenario.expected_lpd)

            # Map style to position quartile
            quartile = _style_to_quartile(profile.style_class)

            # Base win rate from lookup
            key = f"{quartile}_{pace_bucket}_{zone}_{surface}"
            cell = win_rates.get(key)
            base_rate = cell["win_rate"] if cell else 0.10

            # Ability adjustment: scale by relative ability
            # A horse 10 PR pts above field avg gets ~2x the base rate
            ability_diff = profile.ability_estimate - field_avg
            ability_multiplier = 2.0 ** (ability_diff / 10.0)
            adjusted_rate = base_rate * ability_multiplier

            scenario_probs[scenario.label] = adjusted_rate

        # Normalize scenario probs won't be done individually —
        # we normalize across all horses within each scenario below
        contenders.append(ContenderAnalysis(
            horse=profile.horse,
            overall_prob=0.0,
            style_profile=profile,
            scenario_probs=scenario_probs,
            sensitivity=0.0,
            best_scenario="",
            worst_scenario="",
        ))

    # Normalize: within each scenario, probabilities must sum to 1.0
    for scenario in scenarios:
        total = sum(c.scenario_probs[scenario.label] for c in contenders)
        if total > 0:
            for c in contenders:
                c.scenario_probs[scenario.label] /= total

    # Overall probability: weighted average across scenarios
    for c in contenders:
        c.overall_prob = sum(
            scenario.probability * c.scenario_probs[scenario.label]
            for scenario in scenarios
        )
        # Scenario sensitivity
        probs = list(c.scenario_probs.values())
        c.sensitivity = max(probs) - min(probs) if probs else 0.0
        c.best_scenario = max(c.scenario_probs, key=c.scenario_probs.get)
        c.worst_scenario = min(c.scenario_probs, key=c.scenario_probs.get)

    # Sort by overall probability descending
    contenders.sort(key=lambda c: c.overall_prob, reverse=True)

    # Round probabilities for display
    for c in contenders:
        c.overall_prob = round(c.overall_prob, 3)
        c.sensitivity = round(c.sensitivity, 3)
        c.scenario_probs = {k: round(v, 3) for k, v in c.scenario_probs.items()}

    return contenders


def _lpd_to_bucket(lpd: float) -> str:
    if lpd > -20:
        return "held"
    elif lpd > -35:
        return "normal"
    else:
        return "collapse"


def _style_to_quartile(style_class: str) -> int:
    """Map style class to position quartile (1=front, 4=back)."""
    return {"E": 1, "EP": 2, "S": 3, "C": 4, "UNKNOWN": 3}.get(style_class, 3)


def _load_win_rates() -> dict:
    """Load pre-computed win rate table."""
    path = os.path.join(os.path.dirname(__file__), "../../data/lookup_tables/win_rates.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}
