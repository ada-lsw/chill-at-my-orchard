"""Verdict and decision support: plain answers built from past seasons.

Pure functions (no data fetching) so each rule is easy to test and explain:
  verdict()         how this season compares with past seasons on the same date
  history_band()    the compare chart's "normal" band, day by day, drawn with verdict()'s own rule
  closest_season()  which past season's curve looks most like this one ("tracking like 2020")
  decision()        will chill reach the variety's target, and when does the decision window open
  summary_line()    the one sentence the glance card shows; built here so wording matches numbers
  trend_sentence()  the long view's sentence: is chill changing here, said only as surely as we know

Chill portions from the Dynamic Model are not strictly additive (the model carries state), so
"chill so far + what a past season added from this date on" is an approximation. We say so in
the Details layer.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import config, seasons


# ---------------------------------------------------------------- verdict

def percentile_rank(value: float, past: list[float]) -> float | None:
    """Share of past seasons (0-100) that had less chill than `value` on the same date."""
    if not past:
        return None
    past_arr = np.asarray(past, dtype=float)
    below = (past_arr < value).sum() + 0.5 * (past_arr == value).sum()
    return round(float(100.0 * below / len(past_arr)), 1)


def verdict(value: float, past: list[float]) -> dict:
    """Low / normal / high band for chill so far, compared with past seasons on this date.

    Color always travels with a word, so the verdict reads without color too.
    """
    rank = percentile_rank(value, past)
    if rank is None:
        return {"band": "unknown", "color": "gray", "percentile": None, "seasons_compared": 0}
    if rank < config.VERDICT_LOW_PCT:
        band, color = "low", "red"
    elif rank > config.VERDICT_HIGH_PCT:
        band, color = "high", "blue"
    else:
        band, color = "normal", "green"
    return {"band": band, "color": color, "percentile": rank, "seasons_compared": len(past)}


def _band_edges(values: list[float]) -> tuple[float, float]:
    """(band_low, band_high) for one day's past-winter values: where verdict()'s word changes.

    band_low is the lowest value with at least VERDICT_LOW_PCT% of winters at or below it;
    band_high is the highest value with at most VERDICT_HIGH_PCT% of winters below it.
    Both always exist: the top value has 100% at or below it, the bottom value 0% below it.
    """
    vals, n = sorted(values), len(values)
    low = next(v for v in vals if 100 * sum(x <= v for x in vals) / n >= config.VERDICT_LOW_PCT)
    high = next(v for v in reversed(vals) if 100 * sum(x < v for x in vals) / n <= config.VERDICT_HIGH_PCT)
    return low, high


def history_band(curves: list[list[float | None]]) -> dict:
    """The compare chart's "normal" band: one low and one high value per day since the season start.

    `curves` are past winters' cumulative chill portions per day (index 0 = Sept 1). The edges sit
    where the glance card's word changes, so the chart and the card always agree: chill below
    band_low reads "low", above band_high "high", in between "normal". Chill exactly on an edge
    can read either way, because verdict() gives tied winters half credit.
    A day with fewer than config.BAND_MIN_SEASONS winters (missing or NaN values are skipped) gets
    None, so index d still means "d days after Sept 1", like the curves.
    """
    low, high = [], []
    for day in range(max((len(c) for c in curves), default=0)):
        values = [c[day] for c in curves if day < len(c) and c[day] is not None and np.isfinite(c[day])]
        edges = _band_edges(values) if len(values) >= config.BAND_MIN_SEASONS else (None, None)
        low.append(edges[0])
        high.append(edges[1])
    return {"band_low": low, "band_high": high}


def closest_season(curve: list[float], past: list[dict]) -> str | None:
    """Past season whose daily chill curve to this date sits closest (smallest RMS gap).

    `past` items need "season" and "curve" (cumulative chill per day from the season start).
    """
    n = len(curve)
    best, best_gap = None, None
    for p in past:
        other = p.get("curve") or []
        if len(other) < n or n == 0:
            continue
        gap = float(np.sqrt(np.mean((np.asarray(curve) - np.asarray(other[:n])) ** 2)))
        if best_gap is None or gap < best_gap:
            best, best_gap = p["season"], gap
    return best


# ---------------------------------------------------------------- decision

def target_date_for(as_of: date) -> date:
    """The decision target date (e.g. Mar 2) in the chill season that contains `as_of`."""
    m, d = config.TARGET_DATE
    season_start_year = as_of.year if as_of.month >= config.CHILL_START[0] else as_of.year - 1
    return date(season_start_year + 1, m, d)


def status_from_share(share: float) -> str:
    """On track / Watch / At risk from the share of past seasons that reach the target."""
    if share >= config.STATUS_ON_TRACK_SHARE:
        return "on_track"
    if share >= config.STATUS_WATCH_SHARE:
        return "watch"
    return "at_risk"


STATUS_WORDS = {"on_track": ("On track", "green"), "watch": ("Watch", "yellow"),
                "at_risk": ("At risk", "red"), "done": ("Target reached", "green")}


def decision(so_far_cp: float, as_of: date, crop: str, target_cp: float,
             scenarios: list[dict]) -> dict:
    """Is the target likely by the target date, and when does the decision window open?

    scenarios: one per past season, each {"season", "added_by_day"}: cumulative chill portions
    that season added from the same calendar date onward, one value per day up to the target
    date (index 0 = as_of). Built by the endpoint from cached station history.
    """
    tdate = target_date_for(as_of)
    out = {"target_cp": target_cp, "target_date": str(tdate), "so_far_cp": round(so_far_cp, 1),
           "progress_pct": progress_pct(so_far_cp, target_cp),
           "seasons_compared": len(scenarios)}

    if so_far_cp >= target_cp:
        out.update(status="done", reached_in=None, projected_range_cp=None)
    else:
        totals = [so_far_cp + (s["added_by_day"][-1] if s["added_by_day"] else 0.0) for s in scenarios]
        reached = sum(t >= target_cp for t in totals)
        share = reached / len(totals) if totals else 0.0
        out.update(
            status=status_from_share(share) if totals else "unknown",
            reached_in={"seasons": reached, "of": len(totals)},
            projected_range_cp=[round(float(np.percentile(totals, 10)), 1),
                                round(float(np.percentile(totals, 90)), 1)] if totals else None,
        )
    words, color = STATUS_WORDS.get(out["status"], ("Unknown", "gray"))
    out["status_words"], out["color"] = words, color

    # Decision window: only for crops with a sourced milestone (pistachio: 55 CP).
    milestone = config.DECISION_MILESTONE_CP.get(crop)
    window = None
    if milestone is not None:
        if so_far_cp >= milestone:
            window = {"milestone_cp": milestone, "already_reached": True}
        else:
            hit_dates = []
            for s in scenarios:
                for i, added in enumerate(s["added_by_day"]):
                    if so_far_cp + added >= milestone:
                        hit_dates.append(as_of + timedelta(days=i))
                        break
            if hit_dates:
                ordinals = sorted(d.toordinal() for d in hit_dates)
                lo = date.fromordinal(int(np.percentile(ordinals, 20)))
                hi = date.fromordinal(int(np.percentile(ordinals, 80)))
                window = {"milestone_cp": milestone, "already_reached": False,
                          "likely_between": [str(lo), str(hi)],
                          "seasons_reaching": len(hit_dates), "of": len(scenarios)}
            else:
                window = {"milestone_cp": milestone, "already_reached": False, "likely_between": None,
                          "seasons_reaching": 0, "of": len(scenarios)}
    out["decision_window"] = window
    out["options"] = config.INTERVENTION_OPTIONS.get(crop, [])
    out["pca_handoff"] = config.PCA_HANDOFF
    out["low_chill_symptoms"] = config.LOW_CHILL_SYMPTOMS
    out["guardrail"] = ("This tool shows chill and timing only. A licensed Pest Control Adviser "
                        "decides whether and how to treat.")
    return out


# ---------------------------------------------------------------- plain-language lines

def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _fmt_month_day(month_day: tuple[int, int]) -> str:
    """A (month, day) setting the way growers say it: (9, 1) -> "Sep 1"."""
    month, day = month_day
    return f"{date(2001, month, day):%b} {day}"


def progress_pct(so_far_cp: float, target_cp: float) -> int | None:
    """Share of the target reached, in whole percent; never 100 before the target is actually reached."""
    if not target_cp:
        return None
    pct = round(100 * so_far_cp / target_cp)
    return min(pct, 99) if so_far_cp < target_cp else pct


def summary_line(variety: str, so_far_cp: float, target_cp: float, verdict_band: str,
                 closest: str | None) -> str:
    """Glance-card sentence: crop and variety first, number paired with its meaning.

    When chill so far and the target print as the same whole number (57.2 and 57), the sentence says
    "about" or "almost all" instead of "57 ... above the 57" or "57 of the 57".
    """
    band_words = {"low": "Less chill than usual so far", "normal": "A normal year so far",
                  "high": "More chill than usual so far"}.get(verdict_band, "Not enough history to compare")
    like = f", most like {closest}" if closest else ""
    so_far, target = f"{so_far_cp:.0f}", f"{target_cp:.0f}"
    if target_cp and so_far_cp >= target_cp:
        amount = (f"about the {target} chill portions they need" if so_far == target
                  else f"{so_far} chill portions, above the {target} they need")
        return f"Your {variety} trees have reached their target: {amount}. {band_words}{like}."
    amount = (f"almost all of the {target} chill portions they need" if so_far == target
              else f"{so_far} of the {target} chill portions they need")
    return f"Your {variety} trees have {amount} ({progress_pct(so_far_cp, target_cp)}%). {band_words}{like}."


def round_to_half(x: float) -> float:
    """Round to the nearest half, the way growers read a number: 3.52 -> 3.5, 2.43 -> 2.5."""
    return round(x * 2) / 2


def half_words(x: float) -> str:
    """A whole or half number as words print it: 3.5 -> '3½', 4.0 -> '4'."""
    whole = int(x)
    return f"{whole}½" if x - whole == 0.5 else f"{whole}"


def how_sure_line() -> str:
    """One plain sentence on how close the estimate usually is, from the hold-out table (config.HOW_SURE_*).

    Uses the combined typical miss over both stations, rounded to a half, and says in how many winters
    that was true, so "usually" is never an overclaim. Per-station numbers are in the Details layer.
    """
    x = half_words(round_to_half(config.HOW_SURE_TYPICAL_MISS_ALL_CP))
    n_stations = len(config.HOW_SURE_WINTERS)
    return (f"In tests where we hid a real weather station, our estimate was usually within about {x} "
            f"chill portions of what it measured ({config.HOW_SURE_WINTERS_WITHIN} of "
            f"{config.HOW_SURE_WINTERS_ALL} winters at {n_stations} stations).")


def decision_line(d: dict) -> str:
    """Glance-card decision sentence. Never names a product, rate or date to apply."""
    s = d["status"]
    if s == "done":
        line = "Your trees have reached their chill target. No chill-related action needed."
    else:
        r = d.get("reached_in") or {}
        lead = {"on_track": "Likely enough chill", "watch": "Could fall short of chill",
                "at_risk": "Likely short of chill"}.get(s, "Chill outlook unknown")
        line = f"{lead}: past weather reached the target in {r.get('seasons', 0)} of {r.get('of', 0)} years."
    w = d.get("decision_window")
    if w and not w.get("already_reached") and w.get("likely_between") and s in ("watch", "at_risk"):
        a, b = w["likely_between"]
        line += (f" Treatment decisions usually happen around {w['milestone_cp']} chill portions,"
                 f" likely between {_fmt_day(a)} and {_fmt_day(b)}.")
    if s in ("watch", "at_risk"):
        line += " Talk to your PCA."
    return line


def trend_sentence(direction: str, season_labels: list[str], per_decade: float | None,
                   typical_cp: float | None) -> str:
    """The long view's sentence about the trend in season-end chill (oldest season first).

    Says "fell" or "rose" only for a clear trend (main.trend_fit decides). The rate comes with its
    meaning: its share of a typical winter here (the median season total). Names no model.
    """
    n = len(season_labels)
    if n == 0:
        return "No past winters with saved data here yet."
    first, last = season_labels[0], season_labels[-1]
    span = first if n == 1 else f"{first} to {last}"
    counted = f"Chill is counted from {_fmt_month_day(config.CHILL_START)} to {_fmt_month_day(seasons.CHILL_END)}."
    if direction == "too few winters":
        winters = f"{n} winter{'s' if n > 1 else ''}"
        return f"Only {winters} of data here ({span}), too few to tell whether chill is changing. {counted}"
    contiguous = int(last[:4]) - int(first[:4]) + 1 == n
    if contiguous:
        lead = f"Over the last {n} winters here ({span})"
    else:
        lead = f"Over {n} winters here between {first} and {last}"
    if direction in ("falling", "rising"):
        verb = "fell" if direction == "falling" else "rose"
        share = f", about {round(100 * abs(per_decade) / typical_cp)}% of a typical winter here" if typical_cp else ""
        return f"{lead}, chill {verb} by about {abs(per_decade):.1f} chill portions per decade{share}. {counted}"
    return f"{lead}, chill shows no clear rise or fall: {n} winters is too few to tell. {counted}"
