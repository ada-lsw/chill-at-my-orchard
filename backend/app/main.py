"""Chill at My Orchard API.

Answers the grower's three questions for any point:
  1. How much chill / GDD so far?          -> /estimate  "chill", "gdd"
  2. How does that compare to past years?   -> /estimate  "history"
  3. What should I expect in 1-2 weeks?     -> /estimate  "projection"
And proves it works:                        -> /validate  (leave one station out)
Plus decision support:                      -> /decision  (will chill reach the target, and when?)
And the long view:                          -> /history   (season-end chill since the 1980s)

Response shapes live in schemas.py (the contract with the frontend).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from . import chill, config, data, decision, forecast, interp, seasons
from .schemas import DecisionResponse, EstimateResponse, HistoryResponse

app = FastAPI(title="Chill at My Orchard", version="0.1.0")
METRICS = ("chill_portions", "chill_hours", "hours_lt_45", "utah_units")


# ---------------------------------------------------------------- helpers

def load_hourly(station_ids, start: date, end: date) -> dict[str, pd.Series]:
    out = {}
    for sid in station_ids:
        try:
            df = data.get_hourly(sid, start, end)
        except Exception:
            continue  # station offline for this window: the estimate just uses the others
        if not df.empty:
            out[sid] = df.set_index("datetime")["temp_F"]
    return out


def clip(s: pd.Series, start: date, end: date) -> pd.Series:
    return s[(s.index >= pd.Timestamp(start)) & (s.index < pd.Timestamp(end) + pd.Timedelta(days=1))]


def daily_curve(s: pd.Series) -> list[float]:
    """Cumulative chill portions at the end of each day of the season (for the chart)."""
    if s.empty:
        return []
    cp = pd.Series(chill.chill_portions(s), index=s.index)
    return [round(float(v), 2) for v in cp.resample("D").last().ffill()]


def estimate_at(lat, lon, elev, start, end, exclude) -> tuple[pd.Series, pd.DataFrame]:
    """Hourly estimate at a point for one window, and the neighbor stations actually used.

    Neighbors are chosen per window: the closest stations from the shared pool
    (interp.candidates) that have data for this window. So a winter before a station opened,
    or after it closed, uses the next closest station instead.
    """
    cands = interp.candidates(data.get_stations(), lat, lon, elev, exclude=exclude)
    hourly = load_hourly(cands["station_id"], start, end)
    neigh = interp.pick_neighbors(hourly, cands, start, end)
    return interp.estimate_series(hourly, neigh, elev), neigh


def pin_elevation(lat, lon) -> tuple[float, str]:
    """Elevation of the pin, falling back to the nearest station when offline."""
    return interp.pin_elevation(data.get_stations(), lat, lon)


def resolve_variety(variety: str | None, crop: str | None) -> tuple[str, dict]:
    """Pick the variety record. Defaults to the first variety of the crop (or of the menu)."""
    if variety:
        if variety not in config.VARIETIES:
            raise HTTPException(404, f"Unknown variety '{variety}'. See /varieties")
        return variety, config.VARIETIES[variety]
    crop = crop or config.CROP_ORDER[0]
    for name, v in config.VARIETIES.items():
        if v["crop"] == crop:
            return name, v
    raise HTTPException(404, f"No variety for crop '{crop}'. See /varieties")


def target_block(name: str, v: dict, so_far_cp: float) -> dict:
    return {"variety": name, "crop": v["crop"], "target_cp": v["target_cp"], "range_cp": v["range_cp"],
            "progress_pct": round(100.0 * so_far_cp / v["target_cp"], 0), "note": v["note"]}


def past_scenarios(lat, lon, elev, exclude, as_of: date, until: date, n: int) -> list[dict]:
    """For each past season: chill portions it added from as_of's calendar date to `until`.

    Runs the Dynamic Model over the whole shifted season so the model's state is right,
    then reads off what was added after the shifted as_of date, one value per day.
    """
    c_start = seasons.chill_season_start(as_of)
    out = []
    for k in range(1, n + 1):
        s0, a0 = seasons.same_window_in(k, c_start, as_of)
        _, u0 = seasons.same_window_in(k, c_start, until)
        est, _ = estimate_at(lat, lon, elev, s0, u0, exclude)
        est = clip(est, s0, u0)
        if est.dropna().empty:
            continue
        cum = pd.Series(chill.chill_portions(est), index=est.index).resample("D").last().ffill()
        before = cum[cum.index <= pd.Timestamp(a0)]
        base = float(before.iloc[-1]) if not before.empty else 0.0  # chill on the shifted as_of date
        after = cum[cum.index >= pd.Timestamp(a0)]
        out.append({"season": f"{s0.year}-{str(s0.year + 1)[-2:]}",
                    "added_by_day": [round(float(v) - base, 2) for v in after]})
    return out


# ---------------------------------------------------------------- endpoints

@app.get("/health")
def health():
    return {"ok": True, "data_source": config.DATA_SOURCE}


@app.get("/stations")
def stations():
    return data.get_stations().to_dict("records")


@app.get("/demo")
def demo():
    return config.DEMO_ORCHARDS


@app.get("/estimate", response_model=EstimateResponse)
def estimate(
    lat: float, lon: float,
    as_of: date = Query(default_factory=date.today),
    crop: str | None = Query(None, description="walnut, pistachio, almond or prune"),
    variety: str | None = Query(None, description="e.g. 'Chandler walnut'; see /varieties"),
    exclude: list[str] = Query(default=[]),
    history_seasons: int = 10,
    range_low_f: float = config.CUSTOM_RANGE_F[0],
    range_high_f: float = config.CUSTOM_RANGE_F[1],
):
    vname, vrec = resolve_variety(variety, crop)
    crop = vrec["crop"]
    elev, elev_source = pin_elevation(lat, lon)

    # 1. So far
    c_start, c_end, complete = seasons.chill_window(as_of)
    est, neigh = estimate_at(lat, lon, elev, c_start, c_end, exclude)
    if est.dropna().empty:
        raise HTTPException(404, "No station data near this point for this season")
    est = clip(est, c_start, c_end)
    so_far = chill.summarize(est, crop, custom_range=(range_low_f, range_high_f))

    g_start, g_end, g_started = seasons.gdd_window(as_of)
    if g_started:
        g_est, _ = estimate_at(lat, lon, elev, g_start, g_end, exclude)
        gdd = chill.summarize(clip(g_est, g_start, g_end), crop)
    else:
        gdd = chill.summarize(pd.Series(dtype=float, index=pd.DatetimeIndex([])), crop)

    # 2. Past years: same window, shifted back; extend 14 days for the climatology projection
    history = []
    for k in range(1, history_seasons + 1):
        h_start, h_end = seasons.same_window_in(k, c_start, c_end)
        h_est, _ = estimate_at(lat, lon, elev, h_start, seasons.plus_days(h_end, 14), exclude)
        if h_est.dropna().empty:
            continue
        at_date = chill.summarize(clip(h_est, h_start, h_end), crop)
        plus14 = chill.summarize(clip(h_est, h_start, seasons.plus_days(h_end, 14)), crop)
        history.append({
            "season": f"{h_start.year}-{str(h_start.year + 1)[-2:]}",
            "at_date": {m: round(at_date[m], 1) for m in METRICS},
            "next_14_days": {m: round(plus14[m] - at_date[m], 1) for m in METRICS},
            "curve": daily_curve(clip(h_est, h_start, seasons.plus_days(h_end, 14))),
        })
    pct = {}
    if history:
        for m in METRICS:
            vals = [h["at_date"][m] for h in history]
            pct[m] = {p: round(float(np.percentile(vals, q)), 1)
                      for p, q in (("p10", 10), ("p50", 50), ("p90", 90))}

    # 3. Next 14 days: live forecast if we're in the present, else the historical median
    projection = {"days": 14}
    live = as_of >= date.today() - timedelta(days=1) and not complete
    if live:
        fc, src = forecast.hourly_forecast(lat, lon)
        fc = fc[fc.index > est.index.max()]
        if not fc.empty:
            combined = pd.concat([est, fc])
            after = chill.summarize(combined, crop)
            projection.update(method="forecast", source=src,
                              added={m: round(after[m] - so_far[m], 1) for m in METRICS})
    if "added" not in projection and history:
        projection.update(method="climatology (median of past seasons)", source="history",
                          added={m: round(float(np.median([h["next_14_days"][m] for h in history])), 1)
                                 for m in METRICS})
    if "added" in projection:
        projection["projected_total"] = {m: round(so_far[m] + projection["added"][m], 1) for m in METRICS}

    # In replay mode we can also show what actually happened next (honest check of the projection)
    if not live and not complete:
        nxt, _ = estimate_at(lat, lon, elev, c_start, seasons.plus_days(c_end, 14), exclude)
        actual_after = chill.summarize(clip(nxt, c_start, seasons.plus_days(c_end, 14)), crop)
        projection["actually_added"] = {m: round(actual_after[m] - so_far[m], 1) for m in METRICS}

    # Verdict: chill portions so far vs. past seasons on the same date
    cp_now = round(so_far["chill_portions"], 1)
    this_curve = daily_curve(est)
    v = decision.verdict(cp_now, [h["at_date"]["chill_portions"] for h in history])
    v["closest_season"] = decision.closest_season(this_curve, history)
    target = target_block(vname, vrec, cp_now)

    return {
        "location": {"lat": lat, "lon": lon, "elev_m": round(elev, 1), "elev_source": elev_source},
        "as_of": str(as_of), "crop": crop, "data_source": config.DATA_SOURCE,
        "summary": decision.summary_line(vname, cp_now, vrec["target_cp"], v["band"], v["closest_season"]),
        "verdict": v,
        "target": target,
        "chill": {"start": str(c_start), "end": str(c_end), "season_complete": complete,
                  **{m: round(so_far[m], 1) for m in METRICS},
                  "hours_counted": so_far["hours_counted"], "hours_missing": so_far["hours_missing"],
                  "custom_range": so_far["custom_range"],
                  "curve": this_curve},
        "gdd": {"start": str(g_start), "end": str(g_end), "started": g_started, "total_c_days": round(gdd["gdd"], 1),
                "method": "single sine", "thresholds_c": gdd["gdd_thresholds_c"]},
        "history": {"seasons": history, "percentiles": pct},
        "projection": projection,
        "neighbors": neigh[["station_id", "name", "dist_km", "elev_m"]].round(1).to_dict("records"),
        "excluded": exclude,
    }


@app.get("/validate")
def validate(station_id: str, as_of: date = Query(default=date(2025, 2, 28))):
    """Hide a station; estimate it from neighbors with and without the elevation adjustment."""
    stations_df = data.get_stations()
    if station_id not in set(stations_df["station_id"]):
        raise HTTPException(404, f"Unknown station {station_id}")
    c_start, c_end, _ = seasons.chill_window(as_of)
    target = stations_df.set_index("station_id").loc[station_id]
    # Same neighbor rules as the app: closest stations from the shared pool with data this winter.
    cands = interp.candidates(stations_df, target.lat, target.lon, target.elev_m, exclude=[station_id])
    hourly = load_hourly(list(cands["station_id"]) + [station_id], c_start, c_end)
    if station_id not in hourly:
        raise HTTPException(404, f"No data for station {station_id} in {c_start}..{c_end}")
    neigh = interp.pick_neighbors(hourly, cands, c_start, c_end)
    summarize = lambda s: chill.summarize(s)  # noqa: E731
    with_elev = interp.leave_one_out(stations_df, hourly, station_id, summarize, neighbors=neigh)
    no_elev = interp.leave_one_out(stations_df, hourly, station_id, summarize, lapse_f_per_m=0.0,
                                   neighbors=neigh)
    return {"season": f"{c_start} to {c_end}", "with_elevation_adjustment": with_elev,
            "no_elevation_adjustment": no_elev, "data_source": config.DATA_SOURCE,
            "generated": datetime.now().isoformat(timespec="seconds")}


@app.get("/varieties")
def varieties():
    """Crop menu (in the team's order) and each variety's chill target."""
    return {"crop_order": config.CROP_ORDER, "varieties": config.VARIETIES}


@app.get("/decision", response_model=DecisionResponse)
def decision_endpoint(
    lat: float, lon: float,
    as_of: date = Query(default_factory=date.today),
    variety: str | None = Query(None, description="e.g. 'Kerman pistachio'; see /varieties"),
    crop: str | None = None,
    exclude: list[str] = Query(default=[]),
    history_seasons: int = 10,
):
    """Is chill likely to reach the variety's target by the target date, and when is the decision window?

    Informs the decision only. Options are types to raise with a licensed PCA, never rates or timing.
    """
    vname, vrec = resolve_variety(variety, crop)
    elev, _ = pin_elevation(lat, lon)
    c_start, c_end, _ = seasons.chill_window(as_of)
    est, _ = estimate_at(lat, lon, elev, c_start, as_of, exclude)
    est = clip(est, c_start, as_of)
    if est.dropna().empty:
        raise HTTPException(404, "No station data near this point for this season")
    so_far_cp = float(chill.chill_portions(est)[-1])
    tdate = decision.target_date_for(as_of)
    scen = past_scenarios(lat, lon, elev, exclude, as_of, tdate, history_seasons) if as_of < tdate else []
    d = decision.decision(so_far_cp, as_of, vrec["crop"], vrec["target_cp"], scen)
    return {"variety": vname, "crop": vrec["crop"], "as_of": str(as_of), "chill_start": str(c_start),
            "line": decision.decision_line(d), **d}


@app.get("/history", response_model=HistoryResponse)
def history_endpoint(lat: float, lon: float, as_of: date = Query(default_factory=date.today),
                     max_seasons: int = 15, exclude: list[str] = Query(default=[])):
    """Season-end chill portions at the pin for past seasons, with a trend (Julia's long-horizon ask).

    v1 rebuilds each season from hourly station data, which is slow for decades of CIMIS data.
    Work package B2 replaces this with FNRIC's daily chill history per station (one request each).
    """
    elev, elev_source = pin_elevation(lat, lon)
    c_start = seasons.chill_season_start(as_of)
    rows = []
    for k in range(1, max_seasons + 1):
        s0, e0 = seasons.same_window_in(k, c_start, date(c_start.year + 1, *seasons.CHILL_END))
        est, _ = estimate_at(lat, lon, elev, s0, e0, exclude)
        est = clip(est, s0, e0)
        if est.dropna().empty:
            continue
        rows.append({"season": f"{s0.year}-{str(s0.year + 1)[-2:]}",
                     "chill_portions": round(float(chill.chill_portions(est)[-1]), 1)})
    rows.sort(key=lambda r: r["season"])
    trend = None
    if len(rows) >= 5:
        x = np.array([int(r["season"][:4]) for r in rows]); y = np.array([r["chill_portions"] for r in rows])
        trend = round(float(np.polyfit(x, y, 1)[0] * 10), 1)
    return {"location": {"lat": lat, "lon": lon, "elev_m": round(elev, 1), "elev_source": elev_source},
            "season_end": f"{seasons.CHILL_END[0]:02d}-{seasons.CHILL_END[1]:02d}",
            "seasons": rows, "trend_cp_per_decade": trend, "source": config.DATA_SOURCE}
