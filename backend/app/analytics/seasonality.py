"""Seasonality maths (pure functions).

Works on a price history of (date, value) pairs, oldest first. For prices the move is a % change; for
yields ("bp" mode) it is the change in basis points. Only complete calendar months are used, and the current
(unfinished) year is kept apart so it can be compared with the average.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _move(a: float, b: float, mode: str) -> float | None:
    if mode == "bp":
        return round((b - a) * 100, 2)
    return round((b / a - 1) * 100, 3) if a else None


def month_closes(obs: list[tuple[date, float]]) -> dict[tuple[int, int], float]:
    """Last value of each calendar month."""
    out: dict[tuple[int, int], float] = {}
    for d, v in obs:
        out[(d.year, d.month)] = v
    return out


def monthly_moves(obs: list[tuple[date, float]], mode: str = "pct", today: date | None = None
                  ) -> dict[tuple[int, int], float]:
    """Move in each complete month: close of the month vs close of the month before."""
    today = today or date.today()
    closes = month_closes(obs)
    out = {}
    for (y, m), v in closes.items():
        if (y, m) == (today.year, today.month):
            continue  # month not finished yet
        prev = closes.get((y - 1, 12) if m == 1 else (y, m - 1))
        if prev is not None:
            mv = _move(prev, v, mode)
            if mv is not None:
                out[(y, m)] = mv
    return out


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "avg": None, "median": None, "win_rate": None, "best": None, "worst": None}
    return {"n": len(vals), "avg": round(statistics.fmean(vals), 3), "median": round(statistics.median(vals), 3),
            "win_rate": round(100 * sum(1 for v in vals if v > 0) / len(vals)), "best": max(vals), "worst": min(vals)}


def month_stats(moves: dict[tuple[int, int], float], years: int, today: date | None = None) -> list[dict]:
    """For each calendar month over the last `years` complete years: average, median, win rate, best, worst."""
    today = today or date.today()
    first = today.year - years
    out = []
    for m in range(1, 13):
        vals = [v for (y, mm), v in moves.items() if mm == m and first <= y < today.year]
        out.append({"month": m, "name": MONTHS[m - 1], **_stats(vals)})
    return out


# ---------------------------------------------------------------- weeks of the year

def week_of(d: date) -> int:
    """ISO week number, with the rare week 53 folded into week 52."""
    return min(d.isocalendar()[1], 52)


def week_label(w: int, year: int | None = None) -> str:
    """'W43 (20 Oct)': the Monday the week starts on, in the given (or current) year."""
    y = year or date.today().year
    try:
        start = date.fromisocalendar(y, w, 1)
    except ValueError:
        return f"W{w}"
    return f"W{w} ({start.day} {MONTHS[start.month - 1]})"


def weekly_moves(obs: list[tuple[date, float]], mode: str = "pct", today: date | None = None
                 ) -> dict[tuple[int, int], float]:
    """Move in each complete ISO week: last close of the week vs last close of the week before."""
    today = today or date.today()
    closes: dict[tuple[int, int], float] = {}
    order: list[tuple[int, int]] = []
    for d, v in obs:
        iso = d.isocalendar()
        k = (iso[0], iso[1])
        if k not in closes:
            order.append(k)
        closes[k] = v
    cur = today.isocalendar()
    out = {}
    for prev, k in zip(order[:-1], order[1:]):
        if k == (cur[0], cur[1]):
            continue  # week not finished
        mv = _move(closes[prev], closes[k], mode)
        if mv is not None:
            out[(k[0], min(k[1], 52))] = mv
    return out


def week_stats(moves: dict[tuple[int, int], float], years: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    first = today.isocalendar()[0] - years
    out = []
    for w in range(1, 53):
        vals = [v for (y, ww), v in moves.items() if ww == w and first <= y < today.isocalendar()[0]]
        out.append({"week": w, "name": week_label(w, today.year), **_stats(vals)})
    return out


def year_grid(moves: dict[tuple[int, int], float], years: int, today: date | None = None) -> list[dict]:
    """One row per year (newest first) with the move in each month and the year's total."""
    today = today or date.today()
    rows = []
    for y in range(today.year, today.year - years - 1, -1):
        cells = [moves.get((y, m)) for m in range(1, 13)]
        if all(c is None for c in cells):
            continue
        rows.append({"year": y, "months": cells})
    return rows


def _value_on(obs: list[tuple[date, float]], idx: dict[date, int], d: date) -> float | None:
    """Last value on or before d (looks back up to 7 days)."""
    for k in range(8):
        i = idx.get(d - timedelta(days=k))
        if i is not None:
            return obs[i][1]
    return None


def seasonal_path(obs: list[tuple[date, float]], years: int, mode: str = "pct", today: date | None = None,
                  step: int = 7) -> dict:
    """Average path through the year (move since the end of the previous year, every `step` days) over the last
    `years` complete years, plus this year's path so far."""
    today = today or date.today()
    idx = {d: i for i, (d, _) in enumerate(obs)}

    def path(y: int, upto: int | None = None) -> list[float | None]:
        base = _value_on(obs, idx, date(y - 1, 12, 31))
        pts = []
        for day in range(0, 366, step):
            d = date(y, 1, 1) + timedelta(days=day)
            if d.year != y or (upto is not None and day > upto):
                break
            v = _value_on(obs, idx, d)
            pts.append(None if base is None or v is None else _move(base, v, mode))
        return pts

    hist = [path(y) for y in range(today.year - years, today.year)]
    hist = [p for p in hist if p and p[0] is not None]
    n = max((len(p) for p in hist), default=0)
    avg = []
    for i in range(n):
        vals = [p[i] for p in hist if i < len(p) and p[i] is not None]
        avg.append(round(statistics.fmean(vals), 3) if vals else None)
    cur = path(today.year, (today - date(today.year, 1, 1)).days)
    base = _value_on(obs, idx, date(today.year - 1, 12, 31))
    dates = [(date(today.year, 1, 1) + timedelta(days=i * step)).isoformat() for i in range(n)]
    # where price stands against its seasonal path today
    at = len([c for c in cur]) - 1
    gap = None
    if at >= 0 and at < len(avg) and cur and cur[-1] is not None and avg[at] is not None:
        gap = round(cur[-1] - avg[at], 3)
    return {"step_days": step, "average": avg, "current": cur, "years_used": len(hist), "dates": dates,
            "base": base, "today_index": at, "gap_vs_average": gap}


def forward_window(obs: list[tuple[date, float]], years: int, days: int = 30, mode: str = "pct",
                   today: date | None = None) -> dict | None:
    """What happened over the next `days` calendar days from today's date in each past year."""
    today = today or date.today()
    idx = {d: i for i, (d, _) in enumerate(obs)}
    vals = []
    for y in range(today.year - years, today.year):
        try:
            start = today.replace(year=y)
        except ValueError:  # 29 February
            start = today.replace(year=y, day=28)
        a, b = _value_on(obs, idx, start), _value_on(obs, idx, start + timedelta(days=days))
        if a is not None and b is not None:
            mv = _move(a, b, mode)
            if mv is not None:
                vals.append(mv)
    if not vals:
        return None
    return {"days": days, "n": len(vals), "avg": round(statistics.fmean(vals), 3),
            "median": round(statistics.median(vals), 3),
            "win_rate": round(100 * sum(1 for v in vals if v > 0) / len(vals))}


def to_price(base: float, move: float | None, mode: str) -> float | None:
    """Turn a move since the start of the year back into a price (or yield)."""
    if move is None or base is None:
        return None
    return round(base + move / 100, 4) if mode == "bp" else round(base * (1 + move / 100), 6)


def bias(stat: dict | None, min_n: int = 5) -> str:
    """Bullish / Bearish / Mixed for one month's stats: needs a clear average and a win rate of 65%+ (or 35%-)."""
    if not stat or not stat.get("n") or stat["n"] < min_n or stat.get("avg") is None:
        return "Not enough data"
    if stat["win_rate"] >= 65 and stat["avg"] > 0:
        return "Bullish"
    if stat["win_rate"] <= 35 and stat["avg"] < 0:
        return "Bearish"
    return "Mixed"
