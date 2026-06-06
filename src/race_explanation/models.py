"""Data models for the race explanation system."""
from dataclasses import dataclass, field


@dataclass
class RunningStyleProfile:
    horse: str
    style_class: str            # E, EP, S, C, UNKNOWN
    slope_type: str             # Speed, Even, Stamina
    position_score: float       # 0-1 (lower = more forward)
    median_slope: float         # PR points per call
    ability_estimate: float     # recency-weighted pr_finish
    n_starts_used: int
    pct_in_front_group: float   # fraction of starts in front group
    avg_pr_2f: float            # early speed capability
    versatility: float          # std of position fraction

    # Pace dependency (null if < 8 starts)
    pace_correlation: float | None = None
    pace_differential: float | None = None

    @property
    def confidence(self) -> str:
        if self.n_starts_used >= 8:
            return "HIGH"
        elif self.n_starts_used >= 5:
            return "MEDIUM"
        elif self.n_starts_used >= 3:
            return "LOW"
        return "MINIMAL"


@dataclass
class PaceScenario:
    label: str              # "uncontested", "contested", "collapse"
    expected_lpd: float     # center of expected LPD range
    probability: float      # 0-1
    description: str        # "Horse A on uncontested lead"


@dataclass
class Signal:
    type: str           # category of signal
    strength: float     # 0-1, how notable
    description: str    # plain language explanation
    evidence: str       # the specific numbers backing it up


@dataclass
class FormEstimate:
    current_level: float
    confidence: float
    trend: float
    trend_direction: str
    typical_slope: float
    n_starts: int
    days_since_last: int


@dataclass
class ContenderAnalysis:
    horse: str
    overall_prob: float
    style_profile: RunningStyleProfile
    scenario_probs: dict[str, float]    # {scenario_label: probability}
    sensitivity: float                  # max - min across scenarios
    best_scenario: str
    worst_scenario: str
    form: FormEstimate | None = None
    signals: list[Signal] = field(default_factory=list)
    narrative: str = ""


@dataclass
class Contingency:
    condition: str          # "If Horse A and B duel"
    probability: float      # P(this condition)
    beneficiaries: list[str] = field(default_factory=list)
    outcome: str = ""


@dataclass
class Disagreement:
    horse: str
    model_prob: float
    market_prob: float
    edge: float             # model - market
    reason: str = ""


@dataclass
class RaceExplanation:
    race_id: int | None
    track: str
    date: str
    distance: str
    surface: str
    field_size: int
    pace_summary: str
    scenarios: list[PaceScenario]
    contenders: list[ContenderAnalysis]
    key_contingencies: list[Contingency] = field(default_factory=list)
    market_disagreements: list[Disagreement] = field(default_factory=list)
