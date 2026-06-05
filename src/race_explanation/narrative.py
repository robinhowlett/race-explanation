"""Template-based narrative generation from structured race analysis."""
from .models import RaceExplanation, ContenderAnalysis, PaceScenario, Contingency


def generate_narrative(explanation: RaceExplanation) -> dict:
    """Generate text narratives from the structured explanation."""
    return {
        "race_summary": _race_summary(explanation),
        "pace_assessment": _pace_assessment(explanation.scenarios),
        "contenders": [_contender_narrative(c, explanation) for c in explanation.contenders[:5]],
        "key_question": _key_contingency(explanation),
    }


def _race_summary(exp: RaceExplanation) -> str:
    return (f"{exp.field_size}-horse field at {exp.track} "
            f"{exp.distance} {exp.surface}. {exp.pace_summary}")


def _pace_assessment(scenarios: list[PaceScenario]) -> str:
    most_likely = max(scenarios, key=lambda s: s.probability)
    return (f"Most likely scenario ({most_likely.probability*100:.0f}%): "
            f"{most_likely.description}.")


def _contender_narrative(c: ContenderAnalysis, exp: RaceExplanation) -> str:
    profile = c.style_profile
    prob_pct = c.overall_prob * 100

    # Style description
    style_map = {
        "E": "Front-runner",
        "EP": "Early presser",
        "S": "Stalker",
        "C": "Closer",
        "UNKNOWN": "Unknown style",
    }
    style_desc = style_map.get(profile.style_class, "")

    slope_map = {
        "Speed": "who may fade late",
        "Even": "with even energy distribution",
        "Stamina": "who finishes strongly",
    }
    slope_desc = slope_map.get(profile.slope_type, "")

    # Best/worst scenario
    best_prob = c.scenario_probs.get(c.best_scenario, 0) * 100
    worst_prob = c.scenario_probs.get(c.worst_scenario, 0) * 100

    # Build narrative
    parts = [f"{c.horse} ({prob_pct:.0f}%): {style_desc} {slope_desc}."]

    if c.sensitivity > 0.05:
        parts.append(
            f"Chances range from {worst_prob:.0f}% ({c.worst_scenario}) "
            f"to {best_prob:.0f}% ({c.best_scenario})."
        )

    # Key risk based on style
    if profile.style_class == "E":
        parts.append("Risk: if challenged early, may not sustain.")
    elif profile.style_class == "C":
        parts.append("Risk: needs pace to materialize; vulnerable if speed gets away.")
    elif profile.style_class == "EP":
        parts.append("Risk: caught between leading and stalking if pace is irregular.")

    return " ".join(parts)


def _key_contingency(exp: RaceExplanation) -> str:
    """Identify the pivotal question for this race."""
    speed_horses = [c for c in exp.contenders if c.style_profile.style_class == "E"]
    closers = [c for c in exp.contenders if c.style_profile.style_class == "C"]

    if len(speed_horses) >= 2:
        h1 = speed_horses[0].horse
        h2 = speed_horses[1].horse
        beneficiary = closers[0].horse if closers else "stalkers"
        return (f"Key question: Will {h1} and {h2} engage in a speed duel? "
                f"If yes: {beneficiary} benefits as pace collapses. "
                f"If no: the lone speed controls and closers are left flat-footed.")
    elif len(speed_horses) == 1:
        h1 = speed_horses[0].horse
        challenger = exp.contenders[1].horse if len(exp.contenders) > 1 else "the field"
        return (f"Key question: Does {h1} get an uncontested lead? "
                f"If yes: {h1} is dangerous on an easy lead. "
                f"If challenged by {challenger}: pace quickens, opening the door for closers.")
    else:
        return ("Key question: Who takes the lead in a field with no confirmed speed? "
                "Expect a tactical, slow-pace race where positioning matters more than finishing kick.")
