"""Pace scenario projection from field composition.

Given the running style profiles of all entered horses, project
what pace scenario will likely develop and assign probabilities.
"""
import json
import os
from .models import PaceScenario, RunningStyleProfile


def project_pace(profiles: list[RunningStyleProfile], distance_feet: int, surface: str) -> list[PaceScenario]:
    """Project pace scenarios from the field's style profiles.

    Returns 3 scenarios with probabilities summing to 1.0.
    """
    zone = "sprint" if distance_feet <= 4290 else "route"

    # Identify speed horses
    speed_horses = [p for p in profiles if p.style_class == "E"]
    pressers = [p for p in profiles if p.style_class == "EP"]

    n_speed = len(speed_horses)
    n_press = len(pressers)

    # Rank speed horses by early ability
    speed_horses.sort(key=lambda p: p.avg_pr_2f, reverse=True)

    # Determine speed quality gap (if 2+ speed horses)
    speed_gap = 0
    if n_speed >= 2:
        speed_gap = speed_horses[0].avg_pr_2f - speed_horses[1].avg_pr_2f

    # Load LPD distribution for calibration
    lpd_table = _load_lpd_table()

    # Base scenario probabilities from speed count
    if n_speed == 0:
        # No confirmed speed — slow pace likely, but a presser may take over
        if n_press >= 2:
            scenarios = _make_scenarios(
                uncontested=(0.50, -18, f"{pressers[0].horse} likely to inherit lead"),
                contested=(0.35, -25, f"Multiple pressers may engage"),
                collapse=(0.15, -40, "Unlikely without confirmed speed"),
            )
        else:
            scenarios = _make_scenarios(
                uncontested=(0.70, -15, "Slow pace expected — no confirmed speed"),
                contested=(0.20, -22, "Moderate if someone decides to press"),
                collapse=(0.10, -38, "Very unlikely — no speed in field"),
            )

    elif n_speed == 1:
        horse_name = speed_horses[0].horse
        if speed_horses[0].avg_pr_2f > _field_avg_pr_2f(profiles) + 10:
            # Dominant speed — will likely control
            scenarios = _make_scenarios(
                uncontested=(0.60, -20, f"{horse_name} figures to control on a clear lead"),
                contested=(0.25, -30, f"{horse_name} challenged by a presser"),
                collapse=(0.15, -42, f"{horse_name} presses too hard / gets challenged unexpectedly"),
            )
        else:
            # Moderate sole speed
            scenarios = _make_scenarios(
                uncontested=(0.50, -23, f"{horse_name} on an uncontested lead"),
                contested=(0.30, -32, f"{horse_name} engaged by presser(s)"),
                collapse=(0.20, -42, f"Pace gets away from {horse_name}"),
            )

    elif n_speed == 2:
        h1, h2 = speed_horses[0].horse, speed_horses[1].horse
        if speed_gap > 8:
            # One dominant — the other likely sits
            scenarios = _make_scenarios(
                uncontested=(0.40, -22, f"{h1} has clear speed edge, {h2} may defer"),
                contested=(0.40, -35, f"{h1} and {h2} engage through early stages"),
                collapse=(0.20, -45, f"Speed duel between {h1} and {h2} melts both"),
            )
        else:
            # Matched speed — duel likely
            scenarios = _make_scenarios(
                uncontested=(0.20, -22, f"One backs off — unlikely with matched speed"),
                contested=(0.50, -38, f"{h1} and {h2} likely to duel for the lead"),
                collapse=(0.30, -48, f"Sustained duel between {h1} and {h2} collapses the pace"),
            )

    else:  # 3+ speed horses
        names = ", ".join(p.horse for p in speed_horses[:3])
        scenarios = _make_scenarios(
            uncontested=(0.10, -22, "Unlikely with 3+ speed types"),
            contested=(0.40, -42, f"Multiple speed ({names}) engage"),
            collapse=(0.50, -52, f"Speed meltdown — {names} all press"),
        )

    # Adjust for distance (routes have less extreme collapses)
    if zone == "route":
        for s in scenarios:
            if s.label == "collapse":
                s.probability *= 0.8
            elif s.label == "uncontested":
                s.probability *= 1.1
        _normalize_scenarios(scenarios)

    return scenarios


def _make_scenarios(uncontested, contested, collapse) -> list[PaceScenario]:
    """Create 3 scenario objects from (probability, lpd, description) tuples."""
    return [
        PaceScenario(label="uncontested", expected_lpd=uncontested[1],
                     probability=uncontested[0], description=uncontested[2]),
        PaceScenario(label="contested", expected_lpd=contested[1],
                     probability=contested[0], description=contested[2]),
        PaceScenario(label="collapse", expected_lpd=collapse[1],
                     probability=collapse[0], description=collapse[2]),
    ]


def _normalize_scenarios(scenarios: list[PaceScenario]):
    """Ensure probabilities sum to 1.0."""
    total = sum(s.probability for s in scenarios)
    if total > 0:
        for s in scenarios:
            s.probability = round(s.probability / total, 3)


def _field_avg_pr_2f(profiles: list[RunningStyleProfile]) -> float:
    """Average early speed across the field."""
    vals = [p.avg_pr_2f for p in profiles if p.avg_pr_2f > 0 and p.style_class != "UNKNOWN"]
    return sum(vals) / len(vals) if vals else 100.0


def _load_lpd_table() -> dict:
    """Load pre-computed LPD distribution table."""
    path = os.path.join(os.path.dirname(__file__), "../../data/lookup_tables/lpd_distributions.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}
