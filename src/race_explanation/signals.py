"""Signal detection: finds interesting patterns in a horse's PR history.

Looks for nuances the market might miss:
- Shape changes (improving energy distribution)
- Hidden ability (high PR at intermediate calls despite moderate finish)
- Contextual excuses (bad trip, impossible pace, fast day inflation)
- Closing bursts (gaining ground rapidly between specific calls)
- Style changes (tactical shift from recent pattern)
- Improving trajectory masked by class level
"""
from dataclasses import dataclass


@dataclass
class Signal:
    type: str           # category of signal
    strength: float     # 0-1, how notable
    description: str    # plain language explanation
    evidence: str       # the specific numbers backing it up


def detect_signals(conn, horse: str, race_date, surface: str) -> list[Signal]:
    """Scan a horse's recent history for interesting patterns.

    Returns signals sorted by strength (most notable first).
    """
    # Get last 10 starts with full PR vectors and context
    rows = conn.execute("""
        SELECT pr.pr_2f, pr.pr_4f, pr.pr_5f, pr.pr_6f, pr.pr_7f, pr.pr_1m,
               pr.pr_finish, pr.pr_early, pr.pr_late, pr.pr_slope,
               pr.lpd, pr.front_group_size, pr.positional_gain,
               pr.daily_variant_fps, pr.daily_variant_std,
               pr.pace_line_2f, pr.pace_line_finish,
               pr.trip_flags,
               poc.position as first_pos, poc.tot_len_bhd as first_len_bhd,
               r.number_of_runners, r.distance_compact, r.date,
               s.official_position,
               cl.class_level
        FROM handycapper.performance_ratings pr
        JOIN handycapper.starters s ON s.id = pr.starter_id
        JOIN handycapper.races r ON r.id = pr.race_id
        JOIN handycapper.race_class_levels cl ON cl.race_id = r.id
        LEFT JOIN handycapper.points_of_call poc ON poc.starter_id = s.id AND poc.point = 2
        WHERE s.horse = %(horse)s
          AND r.date < %(date)s
          AND r.surface = %(surface)s
          AND pr.excluded = false
          AND pr.pr_finish IS NOT NULL
        ORDER BY r.date DESC
        LIMIT 10
    """, {"horse": horse, "date": race_date, "surface": surface}).fetchall()

    if len(rows) < 2:
        return []

    signals = []

    signals.extend(_detect_shape_change(rows))
    signals.extend(_detect_hidden_ability(rows))
    signals.extend(_detect_pace_excuse(rows))
    signals.extend(_detect_closing_burst(rows))
    signals.extend(_detect_style_change(rows))
    signals.extend(_detect_improving_trajectory(rows))
    signals.extend(_detect_trouble_discount(rows))

    # Sort by strength
    signals.sort(key=lambda s: s.strength, reverse=True)
    return signals


def _detect_shape_change(rows) -> list[Signal]:
    """Detect improving energy distribution (slope becoming more positive)."""
    signals = []
    if len(rows) < 3:
        return signals

    recent_slopes = [float(r["pr_slope"]) for r in rows[:3] if r["pr_slope"] is not None]
    older_slopes = [float(r["pr_slope"]) for r in rows[3:7] if r["pr_slope"] is not None]

    if len(recent_slopes) >= 2 and len(older_slopes) >= 2:
        recent_avg = sum(recent_slopes) / len(recent_slopes)
        older_avg = sum(older_slopes) / len(older_slopes)
        shift = recent_avg - older_avg

        if shift > 3.0:
            strength = min(1.0, shift / 8.0)
            signals.append(Signal(
                type="shape_improving",
                strength=strength,
                description=f"Energy distribution improving — now finishing stronger relative to par "
                            f"(slope shifted from {older_avg:+.1f} to {recent_avg:+.1f})",
                evidence=f"Recent slopes: {[f'{s:+.1f}' for s in recent_slopes]}, "
                          f"older: {[f'{s:+.1f}' for s in older_slopes]}"
            ))
        elif shift < -3.0:
            strength = min(1.0, abs(shift) / 8.0)
            signals.append(Signal(
                type="shape_declining",
                strength=strength,
                description=f"Energy distribution deteriorating — fading more through races "
                            f"(slope shifted from {older_avg:+.1f} to {recent_avg:+.1f})",
                evidence=f"Recent slopes: {[f'{s:+.1f}' for s in recent_slopes]}, "
                          f"older: {[f'{s:+.1f}' for s in older_slopes]}"
            ))

    return signals


def _detect_hidden_ability(rows) -> list[Signal]:
    """Detect high PR at intermediate calls despite moderate finish.

    A horse running PR 115 at 4f but only PR 100 at finish has more ability
    than the finish figure suggests — they just can't sustain it yet.
    """
    signals = []

    for r in rows[:3]:  # last 3 starts
        # Find the peak PR across all calls
        call_prs = []
        for col in ['pr_2f', 'pr_4f', 'pr_5f', 'pr_6f', 'pr_7f', 'pr_1m']:
            if r[col] is not None:
                call_prs.append((col.replace('pr_', ''), float(r[col])))

        if not call_prs or r['pr_finish'] is None:
            continue

        peak_call, peak_pr = max(call_prs, key=lambda x: x[1])
        finish_pr = float(r['pr_finish'])
        gap = peak_pr - finish_pr

        if gap > 10 and peak_pr > 105:
            strength = min(1.0, gap / 20.0)
            signals.append(Signal(
                type="hidden_ability",
                strength=strength,
                description=f"Showed PR {peak_pr:.0f} at {peak_call} call but only "
                            f"{finish_pr:.0f} at finish ({r['date']}) — has ability but couldn't sustain",
                evidence=f"Peak {peak_call}={peak_pr:.0f}, finish={finish_pr:.0f}, gap={gap:.0f} pts, "
                          f"dist={r['distance_compact']}"
            ))
            break  # only report the most recent instance

    return signals


def _detect_pace_excuse(rows) -> list[Signal]:
    """Detect races where the horse was compromised by an extreme pace scenario.

    A front-runner whose race had LPD < -45 (pace collapsed) ran in an impossible
    situation. Their finish PR underestimates their true ability.
    """
    signals = []

    for r in rows[:3]:
        if r['lpd'] is None or r['first_pos'] is None:
            continue

        lpd = float(r['lpd'])
        pos = r['first_pos']
        n_runners = r['number_of_runners']
        finish = r['official_position']

        # Front-runner in a collapse — excuse for bad finish
        if pos <= 2 and lpd < -40 and finish and finish > n_runners * 0.5:
            strength = min(1.0, (abs(lpd) - 40) / 20.0)
            signals.append(Signal(
                type="pace_excuse_speed",
                strength=strength,
                description=f"Led into a pace collapse (LPD {lpd:.0f}) on {r['date']} and "
                            f"finished {finish}th — impossible trip for a front-runner",
                evidence=f"Position 1-2 at first call, LPD={lpd:.0f}, finished {finish}/{n_runners}"
            ))
            break

        # Closer in a held-pace race — never got their trip
        if pos >= n_runners * 0.6 and lpd > -18 and finish and finish > 3:
            pr_finish = float(r['pr_finish']) if r['pr_finish'] else 0
            # Only flag if the horse has shown better ability elsewhere
            best_pr = max((float(r2['pr_finish']) for r2 in rows if r2['pr_finish']), default=0)
            if best_pr - pr_finish > 8:
                strength = min(1.0, (best_pr - pr_finish) / 15.0)
                signals.append(Signal(
                    type="pace_excuse_closer",
                    strength=strength,
                    description=f"Closer who never got pace help (LPD {lpd:.0f}) on {r['date']}. "
                                f"Ran PR {pr_finish:.0f} but has shown {best_pr:.0f}",
                    evidence=f"Back position ({pos}/{n_runners}), LPD={lpd:.0f} (held pace), "
                              f"best prior PR={best_pr:.0f}"
                ))
                break

    return signals


def _detect_closing_burst(rows) -> list[Signal]:
    """Detect a rapid gain between specific calls — the horse accelerated.

    Look at the gap between pr_early and pr_late, or between specific calls.
    A horse that gained significant ground between calls shows a burst of speed.
    """
    signals = []

    for r in rows[:3]:
        if r['pr_early'] is None or r['pr_late'] is None:
            continue

        early = float(r['pr_early'])
        late = float(r['pr_late'])
        burst = late - early

        if burst > 12:
            # Also check positional gain
            pos_gain = r['positional_gain'] or 0
            strength = min(1.0, burst / 20.0)
            signals.append(Signal(
                type="closing_burst",
                strength=strength,
                description=f"Explosive late move on {r['date']} — PR went from {early:.0f} (early) "
                            f"to {late:.0f} (late), gaining {pos_gain} positions",
                evidence=f"PR early={early:.0f}, late={late:.0f}, burst={burst:+.0f}, "
                          f"positional_gain={pos_gain}"
            ))
            break

    return signals


def _detect_style_change(rows) -> list[Signal]:
    """Detect a recent tactical shift from established pattern."""
    signals = []
    if len(rows) < 4:
        return signals

    # Compare position in last 2 starts vs previous 3-5
    recent_pos = []
    older_pos = []
    for i, r in enumerate(rows):
        if r['first_pos'] and r['number_of_runners']:
            frac = r['first_pos'] / r['number_of_runners']
            if i < 2:
                recent_pos.append(frac)
            elif i < 6:
                older_pos.append(frac)

    if len(recent_pos) >= 1 and len(older_pos) >= 2:
        recent_avg = sum(recent_pos) / len(recent_pos)
        older_avg = sum(older_pos) / len(older_pos)
        shift = older_avg - recent_avg  # positive = moved forward

        if shift > 0.25:
            # Moved forward — more aggressive tactics
            strength = min(1.0, shift / 0.4)
            signals.append(Signal(
                type="style_change_forward",
                strength=strength,
                description=f"Tactical shift — now racing more forwardly "
                            f"(position avg {older_avg:.2f} → {recent_avg:.2f})",
                evidence=f"Recent positions: {[f'{p:.2f}' for p in recent_pos]}, "
                          f"older: {[f'{p:.2f}' for p in older_pos]}"
            ))
        elif shift < -0.25:
            # Dropped back — more patient tactics
            strength = min(1.0, abs(shift) / 0.4)
            signals.append(Signal(
                type="style_change_back",
                strength=strength,
                description=f"Tactical shift — now racing from further back "
                            f"(position avg {older_avg:.2f} → {recent_avg:.2f})",
                evidence=f"Recent positions: {[f'{p:.2f}' for p in recent_pos]}, "
                          f"older: {[f'{p:.2f}' for p in older_pos]}"
            ))

    return signals


def _detect_improving_trajectory(rows) -> list[Signal]:
    """Detect a horse whose pr_finish is steadily improving across starts."""
    signals = []
    if len(rows) < 4:
        return signals

    finishes = [float(r['pr_finish']) for r in rows[:6] if r['pr_finish'] is not None]
    if len(finishes) < 4:
        return signals

    # Check if there's a clear upward trend (most recent > older)
    recent = finishes[:3]
    older = finishes[3:]
    if not older:
        return signals

    recent_avg = sum(recent) / len(recent)
    older_avg = sum(older) / len(older)
    improvement = recent_avg - older_avg

    if improvement > 5:
        # Also check monotonicity (is each start better than the one before?)
        improving_count = sum(1 for i in range(len(finishes)-1) if finishes[i] > finishes[i+1])
        strength = min(1.0, improvement / 12.0)
        signals.append(Signal(
            type="improving_trajectory",
            strength=strength,
            description=f"On an upward trajectory — recent avg PR {recent_avg:.0f} vs older "
                        f"avg {older_avg:.0f} ({improvement:+.0f} points improvement)",
            evidence=f"PR sequence (most recent first): {[f'{f:.0f}' for f in finishes]}"
        ))

    elif improvement < -5:
        strength = min(1.0, abs(improvement) / 12.0)
        signals.append(Signal(
            type="declining_trajectory",
            strength=strength,
            description=f"Declining form — recent avg PR {recent_avg:.0f} vs older "
                        f"avg {older_avg:.0f} ({improvement:+.0f} points decline)",
            evidence=f"PR sequence (most recent first): {[f'{f:.0f}' for f in finishes]}"
        ))

    return signals


def _detect_trouble_discount(rows) -> list[Signal]:
    """Detect races where trip trouble suppressed the PR.

    If a horse had 'steadied' or 'blocked' and their PR was below their
    recent average, the trouble may explain the underperformance.
    """
    signals = []
    if len(rows) < 3:
        return signals

    # Baseline ability from clean races
    clean_prs = [float(r['pr_finish']) for r in rows
                 if r['pr_finish'] and (not r['trip_flags'] or r['trip_flags'] == '')]
    if len(clean_prs) < 2:
        return signals
    clean_avg = sum(clean_prs) / len(clean_prs)

    # Check most recent starts for trouble
    for r in rows[:2]:
        if not r['trip_flags']:
            continue
        flags = r['trip_flags']
        pr = float(r['pr_finish']) if r['pr_finish'] else 0

        if any(f in flags for f in ['steadied', 'blocked', 'bumped', 'checked']):
            discount = clean_avg - pr
            if discount > 5:
                strength = min(1.0, discount / 12.0)
                trouble_type = flags.split(',')[0]
                signals.append(Signal(
                    type="trouble_discount",
                    strength=strength,
                    description=f"Was '{trouble_type}' on {r['date']} — ran PR {pr:.0f} "
                                f"vs clean avg of {clean_avg:.0f}. Lost ~{discount:.0f} pts to trouble",
                    evidence=f"Trip flags: {flags}, PR={pr:.0f}, clean_avg={clean_avg:.0f}, "
                              f"discount={discount:.0f}"
                ))
                break

    return signals
