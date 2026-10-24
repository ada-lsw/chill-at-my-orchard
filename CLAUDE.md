# Chill at My Orchard

Team project for the Reboot the Earth Hackathon (UC Davis x UN, Oct 23–24, 2026), Chill Hours Challenge from the UC Davis Fruit and Nut Research and Information Center (FNRIC). See `README.md` for how to run it and `docs/WORK_PACKAGES.md` for who builds what.

**Goal:** tell a grower, in plain words, how much winter chill their own orchard has, how that compares to past years, what to expect next, and whether chill is likely to fall short of their variety's target, even where the nearest CIMIS station is far away or was removed (Durham, station 12).

**Two demo stories:** Durham walnuts in Butte County (station removed) and Kern pistachios (decision support). Every feature must serve one of them, the grower's three questions, or Julia Stover's three asks in the team plan.

**Deadlines:** no new features after **Saturday noon**; code freeze **Saturday 2:00pm**; submit by **2:45pm**. Judging is on technical execution, creativity, and impact for growers. A smaller thing that works beats a bigger thing that doesn't.

## Start of every session

1. Read this file and `docs/WORK_PACKAGES.md`. Ask the user which package and task they own if they haven't said.
2. Check the branch: never work on `main`. If on `main`, `git pull`, then create a branch named for the task.
3. Restate the task and its "done when" from the work package before writing code.

## How to work with teammates (read this first)

Five people with different experience levels share this repo. Several are new to coding. Everyone must be able to explain their own code to a judge. So:

- **Explain before and after.** Before writing code, say in a few sentences what you plan to change and why. After, summarize what changed in plain language a beginner could follow.
- **Teach, don't just do.** When you use a concept the user may not know (an API call, a pandas resample, a Streamlit rerun), add one sentence explaining it.
- **Keep changes small.** One task per branch and PR. If a request would touch many files or another person's files, propose splitting it.
- **Stay in your lane.** Each file has an owner (table below). Only edit files for the current task. Ask before changing another owner's file or anything shared.
- **Readable over clever.** Short functions, descriptive names, a docstring on every function, comments for anything non-obvious.
- **When asked to explain code,** walk through it step by step and point out edge cases, especially missing data.
- **Say when you're unsure.** If a number, threshold, or API field isn't in the code, the plan, or a source, say so and ask. Never invent one.

## Project structure and owners

```
backend/app/
  config.py         ALL shared settings and crop targets; change values here, never hardcode   shared
  schemas.py        API contract (response shapes); the frontend relies on it                  shared
  data.py           CIMIS fetch, per-season cache, gap filling, synthetic data                 Backend A
  chill.py          chill hours, Utah units, chill portions, GDD                                Backend A
  interp.py         estimate at any point (IDW + elevation lapse rate), validation             Backend A
  decision.py       verdict band, closest season, decision support, plain-language lines       Backend A
  main.py           FastAPI endpoints (/history: Backend B)                                     Backend A
  fnric.py          FNRIC API client and cache (new)                                            Backend B
  forecast.py       Open-Meteo 14-day forecast                                                  Backend A
  seasons.py        season windows                                                              Backend A
backend/tests/      pytest tests (test_golden.py: Backend B)
scripts/            check_cimis.py, warm_cache.py, validation_table.py                         Backend A
frontend/
  app.py            wires the screen parts together; no logic                                   Frontend A
  api.py            the only code that calls the backend                                        shared
  components/picker.py, glance.py                                                               Frontend A
  components/compare.py, history_panel.py, details.py                                           Frontend B
pitch/              pitch, video, table card, validation table                                  Pitch
docs/WORK_PACKAGES.md                                                                            Ada
```

**API contract:** `backend/app/schemas.py`, visible at http://localhost:8000/docs. Adding a field is fine. Renaming or removing one breaks the frontend: only in a PR titled "contract:", and tell the frontend owners.

**Data contract:** every stage reads and writes one hourly table with columns `station_id, lat, lon, elev_m, datetime, temp_F, source, is_filled`. `source` is one of `cimis`, `synthetic`, `forecast`, `interp`, `daily`, or a new source agreed at standup. Don't change it without telling the team.

**Frontend rule:** the frontend never calculates chill or decides wording. It shows what the backend returns, including the ready-made sentences `estimate.summary` and `decision.line`.

## Domain rules (match the existing code)

`backend/app/chill.py` already implements these to match FNRIC. Don't rewrite them with simpler formulas.

- **Chill hours:** `32°F < T <= 45°F` (FNRIC's boundary convention). Also reported: hours at or below 45°F, Utah units (FNRIC's decimal bins), and chill portions (Dynamic Model).
- **Chill start date:** Sept 1 (`config.CHILL_START`), FNRIC's start for the Dynamic Model and the basis of the chill targets. Every result shown to a grower must say what date counting started.
- **Chill targets:** per variety in `config.VARIETIES`, all drafts to confirm with FNRIC. Never hardcode a target elsewhere.
- **GDD:** single-sine method (Zalom et al. 1983) in °C·days, thresholds per crop in `config.GDD_THRESHOLDS_C`, counted from bloom (`config.GDD_START`, Feb 20, an assumption to confirm with FNRIC).
- **Missing data:** gaps up to `config.MAX_FILL_HOURS` (3 hours) are filled by linear interpolation and marked `is_filled`; longer gaps stay missing and are reported as `hours_missing`. Never silently drop or fill gaps beyond that.
- **CIMIS API:** New CIMIS weather data at `https://et.water.ca.gov/StationWeb/GetDataByStationNumber` (`stationNbrs`, `isHourly=true`), with the key in the `Ocp-Apim-Subscription-Key` header, never in the URL. The legacy `/api/data` endpoint rejects New CIMIS keys (CIMIS announced the legacy API as operational only through July 31, 2026). One station and one season per request; `data._cimis_records` splits a request in half if CIMIS says it is too large. Cached as one file per station per season in `data/cache/` by `data.season_hourly`. Never add a code path that loops over many uncached requests.
- **FNRIC API:** public, no key, small budget. Download each station once, cache it, never loop.
- **Decision support guardrail:** in California, recommending agricultural pesticide use, including growth regulators, requires a licensed Pest Control Adviser (PCA). The tool may say whether chill will fall short, when the decision window opens, and which *types* of options exist, always ending with "talk to your PCA". It must never show product rates, mixes, application instructions, or "apply on this date". `tests/test_decision.py` checks the wording.
- **Out of scope:** evapotranspiration (ET), statewide coverage, chatbots.

## Plain-language rules for anything a grower sees

- Name the crop and variety, not the model: "the chill your walnuts need". Model names only in the Details layer.
- Pair every number with its meaning: "74% of what Kerman needs", not "42 CP".
- Color always comes with a word (low, normal, high; on track, watch, at risk).
- Say how sure we are in plain words ("usually within 3 portions"), not statistics.
- °F, and dates the way growers say them ("Feb 21").

## Running, testing, secrets

- **Run without Docker** (works in Codespaces): `cd backend && uvicorn app.main:app --reload`, then in a second terminal `cd frontend && streamlit run app.py`. In VS Code: Run and Debug → Backend + Frontend.
- **Data source:** `DATA_SOURCE=synthetic` (default, no key or internet needed) or `cimis`. Build and test on synthetic; check real data before demo.
- **Real data:** `python scripts/check_cimis.py`, then `python scripts/warm_cache.py`.
- **Verifying a real-data result:** one run is never proof. Also run nearby inputs (other dates, varieties, pins) and check that the outputs make sense together: totals rise over the season, a higher target is reached in fewer past winters, and each status matches its rule. Use this to check the logic, never to pick a demo date or setting by which one looks best.
- **Tests:** `cd backend && python -m pytest -q`. Run before every PR; GitHub Actions runs them on every push. Add a test when you change anything in `backend/app/`.
- **Frontend check:** run the app and click both demo buttons. No red errors, glance card readable.
- **Dependencies:** Python 3.12. Add packages to `backend/requirements.txt` or `frontend/requirements.txt`, and say so in the PR.
- **The CIMIS key** comes from the `CIMIS_APP_KEY` environment variable (a Codespaces secret, or `.env`). **Never hardcode it, print it, log it, or commit it.** The repo and the submission will be public.
- Keep the credits in `README.md` (CIMIS, FNRIC, Open-Meteo, Dynamic Model authors) up to date when adding a data source.

## Definition of done

A task is done when: its "done when" in the work package is true, tests pass, both demo buttons still work, the PR template is filled in, a teammate approved it, and it is merged. Then tick it in the team plan.

## Git

- Work on a branch named for the task (`glance-card`, `fnric-client`), never directly on `main`.
- Commit messages say what changed in plain words.
- Open a small PR into `main` and fill in every section of the template. Another teammate reviews and merges. Pull before every standup.
- If `main` moved while you worked: `git pull origin main` into your branch, rerun tests, then push.
