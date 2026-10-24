# Chill at My Orchard

Reboot the Earth Hackathon (UC Davis x UN, Oct 23–24, 2026) · Chill Hours Challenge

Chill and growing degree days (GDD) for a grower's **own orchard**, with a stated error, in the two places CIMIS fails them: where elevation changes quickly, and where stations were removed (e.g. Durham, station 12, closed July 2025).

It answers the grower's three questions:

1. How much chill or GDD have I accumulated so far?
2. How does that compare to past years?
3. How much should I expect in the next week or two?

## Run it in VS Code (Mac, Windows or Linux)

You need [Python 3.12](https://www.python.org/downloads/), [VS Code](https://code.visualstudio.com/) with the **Python** extension, and Git.

**One-time setup:**

```bash
git clone https://github.com/ada-lsw/chill-at-my-orchard
cd chill-at-my-orchard
python -m venv .venv
```

Activate the environment, then install both sets of libraries:

```bash
# Mac / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r backend/requirements.txt -r frontend/requirements.txt
```

In VS Code: open the `chill-at-my-orchard` folder, then Command Palette → **Python: Select Interpreter** → pick `.venv`.

**The key:** copy `.env.example` to `.env` in the repo root and fill it in. `.env` is git-ignored; never commit it.

```
DATA_SOURCE=cimis
CIMIS_APP_KEY=your-key-here
```

Leave `DATA_SOURCE=synthetic` to work offline with fake data.

**Run:** Run and Debug panel (Ctrl/Cmd+Shift+D) → **Backend + Frontend** → play. Or in two terminals:

```bash
cd backend && uvicorn app.main:app --reload
cd frontend && streamlit run app.py
```

- App: http://localhost:8501
- API docs: http://localhost:8000/docs

**Tests:** `cd backend && python -m pytest -q`

Docker files are kept in the repo as an optional alternative (`docker compose up --build`), but the team runs without it.

## Deploy as one app (Streamlit Community Cloud)

The frontend can reach the backend two ways (`frontend/api.py`):
- **Two processes**, the way you develop: set `BACKEND_URL` and the frontend calls the server over HTTP. VS Code's
  "Backend + Frontend" launch and docker-compose already set it. In two terminals:
  `cd backend && uvicorn app.main:app --reload`, then `cd frontend && BACKEND_URL=http://localhost:8000 streamlit run app.py`.
- **One app**, for the public link: leave `BACKEND_URL` unset and the backend runs inside the Streamlit process (no
  server). The answers are the same JSON. Plain `cd frontend && streamlit run app.py` also runs this way, so backend
  edits show only after restarting Streamlit, and both requirement files must be installed.

Steps on [share.streamlit.io](https://share.streamlit.io):
1. **Create app** from the GitHub repo `ada-lsw/chill-at-my-orchard`, branch `main`, main file `frontend/app.py`.
2. **Advanced settings:** Python 3.12. **Secrets**, at the top level (not under a `[section]`), so Streamlit puts them
   in the environment where `backend/app/config.py` reads them:
   ```toml
   DATA_SOURCE = "cimis"
   CIMIS_APP_KEY = "your-key"
   ```
   Never put the key anywhere else; secrets stay out of the repo.
3. Community Cloud installs the requirements file next to the main file (`frontend/requirements.txt`) before the
   repo root's, so that file must also pull in the backend's packages.
4. Make a QR code of the app's public URL for the table card.

## How it's built

Who builds what: [`docs/WORK_PACKAGES.md`](docs/WORK_PACKAGES.md). Rules for every teammate's Claude: [`CLAUDE.md`](CLAUDE.md).

```
backend/app/   FastAPI: all data and math
  config.py        shared settings and per-variety chill targets
  schemas.py       the API contract (live at /docs)
  data.py          CIMIS fetch, one cache file per station per season, gap filling, synthetic data
  chill.py         chill hours, Utah units, chill portions (Dynamic Model), GDD
  interp.py        estimate at any point: IDW + elevation lapse rate; leave-one-out
  decision.py      verdict band, closest past season, decision support, plain-language lines
  forecast.py      Open-Meteo 14-day forecast, cached for offline demos
  seasons.py       season windows (chill from Sept 1, GDD from bloom)
  main.py          endpoints
frontend/      Streamlit: shows what the backend returns
  app.py           wires the screen parts together
  api.py           the only code that calls the backend
  components/      picker, glance card, compare, long view, details
scripts/       check_cimis.py (test the key), warm_cache.py (cache the demo data)
data/cache/    cached data (git-ignored)
```

| Endpoint | What it answers |
| --- | --- |
| `GET /estimate?lat=&lon=&as_of=&variety=&exclude=` | Chill so far, vs. past years, next 14 days, verdict band, glance sentence |
| `GET /decision?lat=&lon=&as_of=&variety=&exclude=` | Will chill reach the variety's target by Mar 2, and when the decision window opens |
| `GET /history?lat=&lon=` | Season-end chill for past seasons, with a trend |
| `GET /validate?station_id=&as_of=` | Hide a station, estimate it, report the error with and without the elevation adjustment |
| `GET /varieties`, `/demo`, `/stations` | Crop menu and targets, demo orchards, station list |

**Real data:** `python scripts/check_cimis.py`, then `python scripts/warm_cache.py`.

**Decision support informs; it doesn't prescribe.** In California, recommending agricultural pesticide use (including growth regulators) requires a licensed Pest Control Adviser. The tool shows whether chill is likely to fall short, when the decision window opens, and which types of options to raise with a PCA, never rates or application steps.

## Data contract

Every stage reads and writes one hourly table:
`station_id, lat, lon, elev_m, datetime, temp_F, source, is_filled`

## Who owns what

| Package | Files |
| --- | --- |
| Backend A (Ada) | `data.py`, `chill.py`, `interp.py`, `decision.py`, `main.py`, `scripts/` |
| Backend B | `fnric.py`, `tests/test_golden.py`, `/history` |
| Frontend A | `frontend/app.py`, `components/picker.py`, `components/glance.py` |
| Frontend B | `components/compare.py`, `components/history_panel.py`, `components/details.py` |
| Pitch | `pitch/` |

## Team rules

- Work on a branch, open small pull requests into `main`, and pull before every standup.
- Tests run on every push (GitHub Actions). Run them locally with `cd backend && python -m pytest -q`.
- Never commit `.env` or the CIMIS key.
- Code freeze: Saturday 2:00pm.

## Known gaps (TODO)

- [ ] Confirm CIMIS response field names against a real response (`HlyAirTmp`, `Hour`, station coordinates)
- [ ] Pick the foothill demo station (`config.DEMO_ORCHARDS["foothill"]`)
- [ ] Confirm GDD base temperatures with FNRIC (`config.GDD_BASE_F`)
- [ ] Cross-check chill portions for one station against chillR
- [ ] Optional: PRISM fallback for orchards far from any station

## Data and credits

CIMIS (California Department of Water Resources) · Open-Meteo (forecast and elevation; Copernicus DEM) · chill models as described by UC Davis FNRIC · Dynamic Model after Fishman et al. (1987) and Erez et al. (1990), following chillR (Luedeling).
