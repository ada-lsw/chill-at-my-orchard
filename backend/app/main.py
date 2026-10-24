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

import logging
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from scipy import stats

from . import chill, config, data, decision, forecast, interp, seasons
from .schemas import DecisionResponse, EstimateResponse, GlossaryResponse, HistoryResponse

app = FastAPI(title="Chill at My Orchard", version="0.1.0")
METRICS = ("chill_portions", "chill_hours", "hours_lt_45", "utah_units")


# ---------------------------------------------------------------- helpers

def _warn_skipped(station_id: str, year: int, error: Exception) -> None:
    """Log that a station was left out of a season because its data couldn't load.

    The key is hidden (data.hide_key). No traceback is logged, because it would repeat the message
    without the key hidden.
    """
    logging.getLogger(__name__).warning(
        "Station %s, season %s: skipped, data could not load (%s: %s)",
        station_id, seasons.season_label(year), type(error).__name__, data.hide_key(str(error)))


def load_hourly(station_ids, start: date, end: date) -> dict[str, pd.Series]:
    """Hourly °F series from start to end for each station that loads.

    A station that fails to load (offline and not cached, CIMIS down) is logged and left out,
    so the estimate uses the others.
    """
    out = {}
    for sid in station_ids:
        try:
            df = data.get_hourly(sid, start, end)
        except Exception as e:  # noqa: BLE001
            _warn_skipped(sid, data.season_year(start), e)
            continue
        if not df.empty:
            out[sid] = df.set_index("datetime")["temp_F"]
    return out


def clip(s: pd.Series, start: date, end: date) -> pd.Series:
    return s[(s.index >= pd.Timestamp(start)) & (s.index < pd.Timestamp(end) + pd.Timedelta(days=1))]


def daily_curve(s: pd.Series, digits: int = 2) -> list[float]:
    """Cumulative chill portions at the end of each day of the season, rounded to `digits` (2 for the chart)."""
    if s.empty:
        return []
    cp = pd.Series(chill.chill_portions(s), index=s.index)
    return [round(float(v), digits) for v in cp.resample("D").last().ffill()]


def estimate_at(lat, lon, elev, start, end, exclude, saved_only: bool = False) -> tuple[pd.Series, pd.DataFrame]:
    """Hourly estimate at a point for one window, and the neighbor stations actually used.

    Neighbors are chosen per window: the closest stations from the shared pool
    (interp.candidates) that have data for this window. So a winter before a station opened,
    or after it closed, uses the next closest station instead.
    saved_only: use only station data already on this machine, never download (saved_coverage_fn).
    """
    cands = interp.candidates(data.get_stations(), lat, lon, elev, exclude=exclude)
    coverage_fn = saved_coverage_fn if saved_only else season_coverage_fn
    neigh = interp.pick_neighbors(cands, coverage_fn(data.season_year(start)))
    hourly = load_hourly(neigh["station_id"], start, end)
    return interp.estimate_series(hourly, neigh, elev), neigh


def _saved_locally(station_id: str, year: int) -> bool:
    """True if this station-season can be read without asking CIMIS.

    Synthetic data is made on this machine; real data counts only if it is already in data/cache/.
    """
    return config.DATA_SOURCE == "synthetic" or data.is_cached(station_id, year)


def season_coverage_fn(year: int):
    """How much of `year`'s season a station has, for interp.pick_neighbors.

    Two guards keep the app from flooding CIMIS:
    - A closed station that isn't cached counts as having no data, without downloading.
      Most closed stations near our pins have no data since 2016, and warm_cache.py has
      already cached the ones the demo orchards need.
    - A station whose data can't be loaded (offline and not cached) counts as having none,
      so the app keeps working with Wi-Fi off. A warning is logged, so online and offline
      numbers never differ without a trace.
    """
    active = data.get_stations().set_index("station_id")["active"]

    def coverage(station_id: str) -> float:
        """Share of the season's hours with a temperature; 0.0 if closed and uncached, or unloadable."""
        if not bool(active.get(station_id, False)) and not data.is_cached(station_id, year):
            return 0.0
        try:
            return data.season_coverage(station_id, year)
        except Exception as e:  # noqa: BLE001
            _warn_skipped(station_id, year, e)
            return 0.0
    return coverage


def saved_coverage_fn(year: int):
    """Like season_coverage_fn, but a station-season not saved on this machine counts as no data.

    Used by the long view (/history), so asking for many winters never downloads anything.
    """
    coverage = season_coverage_fn(year)
    return lambda station_id: coverage(station_id) if _saved_locally(station_id, year) else 0.0


def pin_elevation(lat, lon, exclude=()) -> tuple[float, str]:
    """Elevation of the pin, falling back to the nearest station that isn't hidden when offline."""
    return interp.pin_elevation(data.get_stations(), lat, lon, exclude=exclude)


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
            "progress_pct": decision.progress_pct(so_far_cp, v["target_cp"]), "note": v["note"]}


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
        out.append({"season": seasons.season_label(s0.year),
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
    history_seasons: int = config.HISTORY_SEASONS,
    range_low_f: float = config.CUSTOM_RANGE_F[0],
    range_high_f: float = config.CUSTOM_RANGE_F[1],
):
    vname, vrec = resolve_variety(variety, crop)
    crop = vrec["crop"]
    elev, elev_source = pin_elevation(lat, lon, exclude)

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
    history, band_curves = [], []
    for k in range(1, history_seasons + 1):
        h_start, h_end = seasons.same_window_in(k, c_start, c_end)
        h_est, _ = estimate_at(lat, lon, elev, h_start, seasons.plus_days(h_end, 14), exclude)
        if h_est.dropna().empty:
            continue
        window = clip(h_est, h_start, seasons.plus_days(h_end, 14))
        at_date = chill.summarize(clip(h_est, h_start, h_end), crop)
        plus14 = chill.summarize(window, crop)
        history.append({
            "season": seasons.season_label(h_start.year),
            "at_date": {m: round(at_date[m], 1) for m in METRICS},
            "next_14_days": {m: round(plus14[m] - at_date[m], 1) for m in METRICS},
            "curve": daily_curve(window),
        })
        # The card ranks 1-decimal numbers (cp_now, at_date), so the band uses the same precision, rounded
        # once from the raw values (rounding the 2-decimal curve again could differ from at_date).
        band_curves.append(daily_curve(window, digits=1))
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
        "history": {"seasons": history, "percentiles": pct,
                    **decision.history_band(band_curves)},
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
    neigh = interp.pick_neighbors(cands, season_coverage_fn(data.season_year(c_start)))
    hourly = load_hourly(list(neigh["station_id"]) + [station_id], c_start, c_end)
    if station_id not in hourly:
        raise HTTPException(404, f"No data for station {station_id} in {c_start}..{c_end}")
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
    return {"crop_order": config.CROP_ORDER, "varieties": config.VARIETIES,
            "crop_context": config.CROP_CONTEXT, "climate_caption": config.CLIMATE_CAPTION}


@app.get("/glossary", response_model=GlossaryResponse)
def glossary():
    """One plain line explaining each number the Details layer shows (config.MEASURE_HELP)."""
    return {"measures": config.MEASURE_HELP}


@app.get("/decision", response_model=DecisionResponse)
def decision_endpoint(
    lat: float, lon: float,
    as_of: date = Query(default_factory=date.today),
    variety: str | None = Query(None, description="e.g. 'Kerman pistachio'; see /varieties"),
    crop: str | None = None,
    exclude: list[str] = Query(default=[]),
    history_seasons: int = config.HISTORY_SEASONS,
):
    """Is chill likely to reach the variety's target by the target date, and when is the decision window?

    Informs the decision only. Options are types to raise with a licensed PCA, never rates or timing.
    """
    vname, vrec = resolve_variety(variety, crop)
    elev, _ = pin_elevation(lat, lon, exclude)
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


def _season_total(lat, lon, elev, start: date, end: date, exclude) -> tuple[dict | None, str | None]:
    """One past winter's chill at the pin from saved station data only: (row, None) or (None, why not).

    A winter still in progress is skipped: its saved file is refreshed daily, which downloads.
    """
    if data.season_year(start) >= data.season_year(date.today()):
        return None, "this winter is not finished yet"
    est, _ = estimate_at(lat, lon, elev, start, end, exclude, saved_only=True)
    est = clip(est, start, end)
    if est.dropna().empty:
        return None, "no saved station data near here for this winter"
    totals = chill.summarize(est)
    return {"chill_portions": round(totals["chill_portions"], 1), "hours_missing": totals["hours_missing"]}, None


def trend_fit(rows: list[dict]) -> dict:
    """Straight-line trend of season totals (oldest first) against the season's start year.

    direction is "falling" or "rising" only when the config.TREND_CONFIDENCE (95%) range of the
    slope stays on one side of zero (t distribution, n - 2 degrees of freedom); otherwise
    "no clear change". per_decade is the slope times 10. line holds the fitted values at the
    first and last season. Fewer than config.MIN_TREND_SEASONS winters: "too few winters".
    """
    if len(rows) < config.MIN_TREND_SEASONS:
        return {"direction": "too few winters", "per_decade": None, "line": None}
    years = np.array([int(r["season"][:4]) for r in rows], dtype=float)
    fit = stats.linregress(years, [r["chill_portions"] for r in rows])
    margin = stats.t.ppf((1 + config.TREND_CONFIDENCE) / 2, len(rows) - 2) * fit.stderr
    if fit.slope + margin < 0:
        direction = "falling"
    elif fit.slope - margin > 0:
        direction = "rising"
    else:
        direction = "no clear change"

    def on_line(i: int) -> dict:
        """The fitted line's value at row i."""
        return {"season": rows[i]["season"], "chill_portions": round(float(fit.intercept + fit.slope * years[i]), 1)}
    return {"direction": direction, "per_decade": round(float(fit.slope * 10), 1),
            "line": {"start": on_line(0), "end": on_line(-1)}}


@app.get("/history", response_model=HistoryResponse)
def history_endpoint(lat: float, lon: float, as_of: date = Query(default_factory=date.today),
                     max_seasons: int = 15, exclude: list[str] = Query(default=[])):
    """Season-end chill portions at the pin for past seasons, with a trend (Julia's long-horizon ask).

    Reads only station data already saved on this machine and never downloads, so asking for
    many winters is safe. Winters it can't count are listed in seasons_skipped with the reason.
    v1 rebuilds each season from hourly station data; work package B3 adds FNRIC's daily chill
    history per station to reach back further.
    """
    elev, elev_source = pin_elevation(lat, lon, exclude)
    c_start = seasons.chill_season_start(as_of)
    rows, skipped = [], []
    for k in range(1, max_seasons + 1):
        s0, e0 = seasons.same_window_in(k, c_start, date(c_start.year + 1, *seasons.CHILL_END))
        label = seasons.season_label(s0.year)
        row, reason = _season_total(lat, lon, elev, s0, e0, exclude)
        if row:
            rows.append({"season": label, **row})
        else:
            skipped.append({"season": label, "reason": reason})
    rows.sort(key=lambda r: r["season"])
    skipped.sort(key=lambda r: r["season"])
    trend = trend_fit(rows)
    typical = float(np.median([r["chill_portions"] for r in rows])) if rows else None
    return {"location": {"lat": lat, "lon": lon, "elev_m": round(elev, 1), "elev_source": elev_source},
            "season_end": f"{seasons.CHILL_END[0]:02d}-{seasons.CHILL_END[1]:02d}",
            "seasons": rows, "trend_cp_per_decade": trend["per_decade"], "source": config.DATA_SOURCE,
            "trend_direction": trend["direction"], "trend_line": trend["line"],
            "trend_sentence": decision.trend_sentence(trend["direction"], [r["season"] for r in rows],
                                                      trend["per_decade"], typical),
            "seasons_used": len(rows), "seasons_skipped": skipped}
