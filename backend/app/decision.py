"""Verdict and decision support: plain answers built from past seasons.

Pure functions (no data fetching) so each rule is easy to test and explain:
  verdict()         how this season compares with past seasons on the same date
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
           "progress_pct": round(100.0 * so_far_cp / target_cp, 0) if target_cp else None,
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


def summary_line(variety: str, so_far_cp: float, target_cp: float, verdict_band: str,
                 closest: str | None) -> str:
    """Glance-card sentence: crop and variety first, number paired with its meaning."""
    pct = round(100 * so_far_cp / target_cp) if target_cp else None
    band_words = {"low": "Less chill than usual so far", "normal": "A normal year so far",
                  "high": "More chill than usual so far"}.get(verdict_band, "Not enough history to compare")
    like = f", most like {closest}" if closest else ""
    if target_cp and so_far_cp >= target_cp:
        return (f"Your {variety} trees have reached their target: {so_far_cp:.0f} chill portions, "
                f"above the {target_cp:.0f} they need. {band_words}{like}.")
    return (f"Your {variety} trees have {so_far_cp:.0f} of the {target_cp:.0f} chill portions they need "
            f"({pct}%). {band_words}{like}.")


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
    counted = (f"Chill is counted from {_fmt_day(date(2001, *config.CHILL_START).isoformat())} "
               f"to {_fmt_day(date(2001, *seasons.CHILL_END).isoformat())}.")
    if direction == "too few winters":
        return f"Only {n} winter{'s' if n > 1 else ''} of data here ({span}), too few to tell whether chill is changing. {counted}"
    contiguous = int(last[:4]) - int(first[:4]) + 1 == n
    lead = f"Over the last {n} winters here ({span})" if contiguous else f"Over {n} winters here between {first} and {last}"
    if direction in ("falling", "rising"):
        verb = "fell" if direction == "falling" else "rose"
        share = f", about {round(100 * abs(per_decade) / typical_cp)}% of a typical winter here" if typical_cp else ""
        return f"{lead}, chill {verb} by about {abs(per_decade):.1f} chill portions per decade{share}. {counted}"
    return f"{lead}, chill shows no clear rise or fall: {n} winters is too few to tell. {counted}"
