"""Validation of manual and automated data (Sections 51 and 66.6).

`validate_release` is pure: callers pass in the history and existing records.
Every warning has a code so the UI can explain it and the user can override it
with a recorded reason."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Warning_:
    code: str
    message: str
    severity: str = "warning"  # warning | error

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "severity": self.severity}


PERIOD_RE = re.compile(r"^(20\d{2})(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?|Q[1-4])?$")  # weekly: week-ending date


def validate_release(
    *,
    indicator_code: str | None,
    indicator_unit: str | None,
    indicator_transform: str | None,
    indicator_frequency: str | None,
    actual: float | None,
    previous: float | None,
    consensus: float | None,
    reference_period: str | None,
    released_at: datetime | None,
    history: list[float],
    existing_same_period: list[dict],
    parsed_transform: str | None = None,
    parsed_unit: str | None = None,
    related_values: dict[str, float] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    w: list[Warning_] = []

    if indicator_code is None:
        w.append(Warning_("UNMAPPED_INDICATOR", "Indicator could not be matched — please choose it", "error"))
    if actual is None:
        w.append(Warning_("MISSING_ACTUAL", "No actual value found", "error"))
    if reference_period is None:
        w.append(Warning_("MISSING_PERIOD", "Reference period missing — please confirm the period", "error"))
    elif not PERIOD_RE.match(reference_period):
        w.append(Warning_("BAD_PERIOD", f"Reference period '{reference_period}' is not in YYYY-MM or YYYYQn form"))
    else:
        if indicator_frequency == "quarterly" and "Q" not in reference_period:
            w.append(Warning_("PERIOD_FREQUENCY", "Quarterly indicator but a monthly period was given"))
        if indicator_frequency == "monthly" and "Q" in reference_period:
            w.append(Warning_("PERIOD_FREQUENCY", "Monthly indicator but a quarterly period was given"))
        y = int(reference_period[:4])
        if y > now.year or (y == now.year and "-" in reference_period and int(reference_period[5:7]) > now.month):
            w.append(Warning_("FUTURE_PERIOD", "Reference period is in the future"))

    if released_at is not None:
        ra = released_at if released_at.tzinfo else released_at.replace(tzinfo=timezone.utc)
        if ra > now:
            w.append(Warning_("FUTURE_RELEASE_TIME", "Release time is in the future"))

    if parsed_transform and indicator_transform and parsed_transform != indicator_transform and \
            not (parsed_transform == "qoq" and indicator_transform == "qoq_saar"):
        w.append(Warning_("TRANSFORM_MISMATCH",
                          f"Value looks like {parsed_transform} but the indicator is {indicator_transform}"))
    if parsed_unit and indicator_unit and parsed_unit != indicator_unit and \
            not (indicator_unit == "index" and parsed_unit == "%"):
        w.append(Warning_("UNIT_MISMATCH", f"Unit '{parsed_unit}' differs from indicator unit '{indicator_unit}'"))

    ref = [v for v in ([previous] if previous is not None else []) + history[-24:] if v is not None]
    if actual is not None and ref:
        last = ref[0] if previous is not None else ref[-1]
        if last not in (0, None) and abs(actual) > 0 and indicator_unit in ("%", "index"):
            ratio = abs(actual / last) if last else 0
            if ratio >= 8 or (0 < ratio <= 0.125 and abs(last) >= 1):
                w.append(Warning_("DECIMAL_SHIFT",
                                  f"{actual} vs previous {last}: possible decimal/OCR error", "error"))
        if len(ref) >= 6:
            diffs = [b - a for a, b in zip(ref[:-1], ref[1:])]
            sd = statistics.pstdev(diffs) or 0.0
            if sd > 0 and abs(actual - last) > 6 * sd and "DECIMAL_SHIFT" not in {x.code for x in w}:
                w.append(Warning_("IMPLAUSIBLE_CHANGE",
                                  f"Change of {actual - last:+.2f} is unusually large vs history (σ={sd:.2f})"))
        if indicator_transform in ("yoy", "level") and indicator_unit == "%" and previous is not None \
                and abs(actual - previous) > 3 and "DECIMAL_SHIFT" not in {x.code for x in w}:
            w.append(Warning_("LARGE_JUMP", f"Moved {actual - previous:+.2f} pts from previous"))
    if consensus is not None and actual is not None and consensus != 0:
        r = abs(actual / consensus)
        if (r >= 8 or r <= 0.125) and abs(consensus) >= 0.5:
            w.append(Warning_("CONSENSUS_SCALE", "Actual and forecast differ by an order of magnitude"))

    for ex in existing_same_period:
        if ex.get("actual") == actual:
            w.append(Warning_("DUPLICATE", f"Same value already stored (release #{ex.get('id')}, "
                                           f"{ex.get('verification_status')})"))
        else:
            w.append(Warning_("CONFLICT_EXISTING",
                              f"A different value {ex.get('actual')} is already stored for this period "
                              f"(release #{ex.get('id')}, {ex.get('verification_status')}). "
                              "Nothing is overwritten: if the stored value is official, yours is kept as a "
                              "conflict for review; otherwise yours becomes current and the old one is kept "
                              "as superseded.", "warning"))

    rel = related_values or {}
    if indicator_code and actual is not None:
        # internal consistency: core vs headline should not differ wildly
        if "CORE" in indicator_code:
            head = rel.get(indicator_code.replace("CORE_", ""))
            if head is not None and abs(head - actual) > 4:
                w.append(Warning_("CORE_HEADLINE_GAP", f"Core {actual} vs headline {head}: check values"))
        else:
            core = rel.get(indicator_code.replace("_CPI", "_CORE_CPI").replace("_PCE", "_CORE_PCE")
                           .replace("_HICP", "_CORE_HICP"))
            if core is not None and abs(core - actual) > 4:
                w.append(Warning_("CORE_HEADLINE_GAP", f"Headline {actual} vs core {core}: check values"))
    return [x.as_dict() for x in w]
