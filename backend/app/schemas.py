"""The API contract: the shapes the frontend can rely on.

FastAPI turns these models into the live docs page at /docs. Frontend teammates build against
those docs (with DATA_SOURCE=synthetic) without waiting for backend work.

Rule: add fields freely, but never rename or remove one without telling the frontend owners
in the PR. Every response says what date counting started.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Open(BaseModel):
    """Base for responses: extra fields are allowed, so adding a field never breaks clients."""
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- shared pieces

class Location(Open):
    lat: float
    lon: float
    elev_m: float
    elev_source: str = Field(description="'open-meteo' or 'nearest station (offline)'")


class Neighbor(Open):
    station_id: str
    name: str | None = None
    dist_km: float
    elev_m: float


class Verdict(Open):
    band: Literal["low", "normal", "high", "unknown"]
    color: Literal["red", "green", "blue", "gray"] = Field(description="Always show with the band word")
    percentile: float | None = Field(description="Share of past seasons with less chill on this date (0-100)")
    seasons_compared: int
    closest_season: str | None = Field(None, description="e.g. '2019-20': past season whose curve looks most like this one")


class Target(Open):
    variety: str
    crop: str
    target_cp: float = Field(description="Chill portions the variety needs (draft, confirm with FNRIC)")
    range_cp: tuple[float, float]
    progress_pct: float | None
    note: str


# ---------------------------------------------------------------- /estimate

class ChillSoFar(Open):
    start: str = Field(description="Date counting started; show it on screen")
    end: str
    season_complete: bool
    chill_portions: float
    chill_hours: float = Field(description="FNRIC hours above 32°F up to 45°F")
    hours_lt_45: float
    utah_units: float
    hours_counted: int
    hours_missing: int
    custom_range: dict = Field(description="hours_below / hours_between / hours_above for the grower's range")
    curve: list[float] = Field(description="Cumulative chill portions at the end of each day since start")


class EstimateResponse(Open):
    location: Location
    as_of: str
    crop: str
    data_source: str
    summary: str = Field(description="One plain sentence for the glance card, already worded")
    verdict: Verdict
    target: Target
    chill: ChillSoFar
    gdd: dict
    history: dict = Field(description="seasons: [{season, at_date, next_14_days, curve}], percentiles, "
                                      "band_low / band_high: per day since the chill start (like curve), "
                                      "the past-winter range the verdict calls normal; null on days with "
                                      "fewer than config.BAND_MIN_SEASONS winters")
    projection: dict
    neighbors: list[Neighbor]
    excluded: list[str]


# ---------------------------------------------------------------- /decision

class DecisionWindow(Open):
    milestone_cp: float
    already_reached: bool
    likely_between: list[str] | None = None
    seasons_reaching: int | None = None
    of: int | None = None


class Option(Open):
    type: str
    detail: str
    source: str


class DecisionResponse(Open):
    variety: str
    crop: str
    as_of: str
    chill_start: str
    status: Literal["on_track", "watch", "at_risk", "done", "unknown"]
    status_words: str
    color: str
    line: str = Field(description="One plain sentence for the glance card, already worded")
    target_cp: float
    target_date: str
    so_far_cp: float
    progress_pct: float | None
    reached_in: dict | None = Field(description="{seasons, of}: past seasons that reached the target")
    projected_range_cp: list[float] | None = Field(description="10th-90th percentile chill by the target date")
    decision_window: DecisionWindow | None = Field(description="Only for crops with a sourced milestone (pistachio)")
    options: list[Option] = Field(description="Types to raise with a PCA. Never rates or timing")
    pca_handoff: str
    low_chill_symptoms: list[str]
    guardrail: str
    seasons_compared: int


# ---------------------------------------------------------------- /history (long horizon)

class SeasonTotal(Open):
    season: str
    chill_portions: float
    hours_missing: int = Field(
        description="Hours inside this winter's estimate where no neighbor station had a reading")


class SkippedSeason(Open):
    season: str
    reason: str = Field(description="Why this winter isn't counted, in plain words")


class TrendPoint(Open):
    season: str
    chill_portions: float


class TrendLine(Open):
    start: TrendPoint = Field(description="The fitted straight line's value at the first season")
    end: TrendPoint = Field(description="The fitted straight line's value at the last season")


class HistoryResponse(Open):
    location: Location
    season_end: str = Field(description="Month-day each season total is counted to")
    seasons: list[SeasonTotal]
    trend_cp_per_decade: float | None
    source: str
    trend_sentence: str = Field(description="One plain sentence about the trend, already worded; always present")
    trend_direction: Literal["falling", "rising", "no clear change", "too few winters"] = Field(
        description="falling or rising only when the confidence range of the slope (config.TREND_CONFIDENCE, "
                    "95%) excludes zero")
    trend_line: TrendLine | None = Field(
        description="Fitted line at the first and last season; null if too few winters")
    seasons_used: int
    seasons_skipped: list[SkippedSeason] = Field(description="Winters not counted (nothing saved, or not finished)")
