# Work packages

Each package has one owner, its own files, and a clear "done when". Packages only meet at two
seams that are already frozen, so nobody waits on anybody:

- **The API contract**: `backend/app/schemas.py`, browsable at http://localhost:8000/docs.
- **The data contract**: one hourly table, `station_id, lat, lon, elev_m, datetime, temp_F, source, is_filled`.

Everyone can build today on **synthetic data** (`DATA_SOURCE=synthetic`), which needs no key or internet.

Deadlines: code freeze **Saturday 2:00pm**, submit by **2:45pm**. No new features after **Saturday noon**.

| Package | Owner | Files you own | First thing to ship |
|---|---|---|---|
| Backend A: real data, proof, hourly-from-daily | Ada | `backend/app/data.py`, `interp.py`, `decision.py`, `main.py`, `scripts/` | Real data cached for both demos |
| Backend B: FNRIC data, golden tests, long view | (name) | `backend/app/fnric.py` (new), `backend/tests/test_golden.py` (new), `/history` in `main.py` | FNRIC client that caches one station |
| Frontend A: picker and glance card | Sevim | `frontend/app.py`, `frontend/components/picker.py`, `glance.py` | Glance card readable on a phone |
| Frontend B: compare, long view, details | Drew | `frontend/components/compare.py`, `history_panel.py`, `details.py` | "Is chill declining here?" long view (from PR #3) |
| Pitch and mentors (optional 5th person) | (name) | `pitch/` | Mentor answers in the Build details tab |

Shared files (`config.py`, `schemas.py`, `api.py`, `CLAUDE.md`): change only through a PR that says so in its
title, and tell the team at standup.

---

## How every task runs

1. `git checkout main && git pull`, then `git checkout -b <short-task-name>`.
2. Start Claude Code and paste: *"Read CLAUDE.md and docs/WORK_PACKAGES.md. I own <package>. My task is
   <task>. Explain your plan before writing code, write a test first if it touches the backend, and keep the
   change small."*
3. Run it: backend `cd backend && python -m pytest -q`; frontend, run the app and click both demo buttons.
4. Open a PR into `main`. Fill in every section of the template. Ask one teammate to review.
5. Tick the task in the team plan doc when it is merged, not before.

Stuck for 20 minutes? Say so in the group chat. That is faster than staying stuck.

---

## Backend A: real data, proof, hourly-from-daily (Ada)

Goal: real numbers for both demo stories, and the proof that they are accurate.

| # | Task | Done when |
|---|---|---|
| A1 | Run `python scripts/check_cimis.py` in a Codespace. Uses the New CIMIS API (see CLAUDE.md, CIMIS API). | All four checks pass |
| A2 | Run `python scripts/warm_cache.py`. Requests that are too large split themselves automatically. | Both demos load with Wi-Fi off |
| A3 | Pick the real Kern pin (a pistachio area) and confirm Shafter (5) as the hold-out. Update `config.DEMO_ORCHARDS`. | Kern demo shows real neighbors |
| A4 | `scripts/validation_table.py`: run `/validate` for every cached station; write `pitch/validation.csv` and a short table. Try `NEIGHBORS` 3 vs 5 and the lapse rate on vs off; ship the lowest error. | The proof table exists, with the settings we ship |
| A5 | Hourly-from-daily (Julia's ask): `backend/app/hourly_from_daily.py`, a port of chillR's `make_hourly_temps` (sine curve by day, logarithmic decay at night, sunrise and sunset from latitude; Linvill 1990). Add a daily-only comparison to `/validate`. Tag rebuilt rows `source="daily"`. | Chill error from daily-only data is in the proof table |
| A6 | One-app deploy on Streamlit Community Cloud (frontend calls backend code in-process when `BACKEND_URL` is unset). | Public link works; QR code made |

Order: A1, A2, A3 tonight or first thing; A4 by Saturday 11am; A5 only if A4 is done; A6 by Saturday 1pm.

## Backend B: FNRIC data, golden tests, long view

Goal: prove our math matches FNRIC, and make the long-term view fast.

FNRIC's API is public, needs no key, and is paid for from a small budget. **Download each station once, cache it,
never loop on requests.** Read the cheat sheet first:
https://github.com/ucdavis/fnric-reboot-the-eath-hackathon (Base URL and endpoints are in it.)

| # | Task | Done when |
|---|---|---|
| B1 | `backend/app/fnric.py`: `stations()` and `daily_chill(station_id)` using `chill-models-download` (CSV of daily `hours_lt_45`, `hours_32_45`, `units_utah`, `portions_dynamic`). Cache each CSV in `data/cache/fnric_<station>.csv`. Station ids look like `CIMIS-6`. Sort by date; values are daily amounts, not totals. | A test loads a cached CSV and sums one season |
| B2 | `backend/tests/test_golden.py`: for Davis (6) and Firebaugh (7), compare our season-to-date totals from cached CIMIS hourly data with FNRIC's for the same dates (season starts Sept 1). Skip the test when no cache exists, so CI stays green. Report the difference. | "Our chill matches FNRIC within X" is a sentence we can say to judges |
| B3 | Make `/history` fast: season-end chill portions at each nearest station from FNRIC daily data, blended by distance (same weights as `interp.py`), back to the 1980s. Keep the response shape in `schemas.HistoryResponse`. | Long view loads in under 5 seconds |
| B4 | Fold in the climate-data PR: new sources must produce the data contract table, with their own `source` value, and document where they came from in `README.md` credits. | Merged with tests |
| B5 | Stretch: bloom frost hours (Julia's brief: whether frost protection may be needed for newly opening buds). `chill.frost_hours(series, threshold_f)` counts hours at or below a threshold, skipping missing hours. Thresholds in `config.py`: `FROST_CRITICAL_F = {"almond": 27.1}` (Parker et al. 2021, verify against the paper) and `FROST_GENERAL_F = 32.0` for other crops. `/estimate` gains `frost: {threshold_f, source, hours_since_bloom, forecast_hours}` from the bloom-window series and the 14-day forecast. Proposed by Drew in PR #3. Only after A4 and B2. | One test in `test_chill.py`; `frost` block in `/estimate` |

## Frontend A: picker and glance card

Goal: a grower understands their orchard in five seconds, on a phone, without reading numbers.

Read the team plan's "Screen design" section first. Rules: name the crop, not the model; every number paired with
its meaning; color always with a word; °F and grower dates; large text, few elements.

| # | Task | Done when |
|---|---|---|
| F1 | Glance card (`glance.py`): one colored box with the verdict word and `est["summary"]`, one with `dec["status_words"]` and `dec["line"]`. Use the backend's sentences; do not write your own wording from numbers. | Reads correctly for both demos |
| F2 | Big, phone-friendly layout: test at a narrow browser width. Keep the glance card above the fold. | Screenshot at phone width in the PR |
| F3 | Share with my PCA: make the link a full URL a grower can paste into a text message, and confirm opening it restores the same orchard, variety and date. | Opening the link in a new tab shows the same card |
| F4 | Picker (`picker.py`): demo buttons first, then crop and variety (menu order from `/varieties`), then the map. | A first-time user finds the demos without help |
| F5 | Demo mode polish: one click per story, no spinners longer than 2 seconds with cached data. | Timed walk-through under 60 seconds |

## Frontend B: compare, long view, details

Goal: the one-tap layers a PCA or a curious grower opens, and the proof judges ask for.

| # | Task | Done when |
|---|---|---|
| G1 | Compare chart (`compare.py`): shade the normal range (10th to 90th percentile of past curves, from `est["history"]["seasons"]`), last season dotted, the target as a line, the next 14 days as a short dashed extension. | One chart reads at 6 feet |
| G2 | Long view, "Is chill declining here?" (`history_panel.py`): port Drew's climate-trend section from PR #3. Season-end chill bars from `/history` (back to the 1980s once B3 lands), the variety's target line, a trend line, and the plain trend sentence (`describe_trend`). Under it, the research caption (Zhang et al. 2021) and a short crop note. Crop notes live in `config.py` as `CROP_CONTEXT`, served by `/varieties`, written in chill portions (not chill hours), with every figure checked against its paper. | Loads for both demos; every on-screen figure has a checked source |
| G5 | Stretch, after B5: show `est["frost"]` as a frost-hours metric and a 14-day frost line in `details.py`. | Shows only when `/estimate` returns a `frost` block |
| G3 | Details (`details.py`): every measure with a one-line tooltip, the grower's temperature range (`est["chill"]["custom_range"]`), options to raise with a PCA with sources, the guardrail sentence, and the proof panel. | Every number has a plain explanation |
| G4 | Data download: a button that downloads the season's daily chill as CSV. | File opens in Excel |

## Pitch and mentors (optional 5th person)

| # | Task | Done when |
|---|---|---|
| P1 | Get answers for the Build details "Answers to get from mentors" table (bloom date, verdict bands, Kerman target, decision date, PCA handoff). | Answer column filled; backend told at standup |
| P2 | Pitch deck around the two stories: Durham walnuts (station removed) and Kern pistachios (decision support). | Rehearsed three times, plus a 90-second version |
| P3 | 60-second demo video, one-page table card with the proof numbers and a QR code, Unite Ideas submission. | Submitted by 2:45pm Saturday |

---

## Checkpoints

| When | All of this is true |
|---|---|
| Fri night | A1 to A3 done; B1 started; F1 and G1 started on synthetic data |
| Sat 11am | A4 proof table, B2 golden test, F1 to F3, G1 to G3 merged |
| Sat noon | Feature freeze. Only fixes after this |
| Sat 1pm | Deployed (A6), runs with Wi-Fi off, video recorded |
| Sat 2pm | Code frozen |
