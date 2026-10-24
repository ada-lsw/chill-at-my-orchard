# Validation: how close is the estimate where a station is hidden?

Made by `scripts/validation_table.py` from saved CIMIS hourly data (no downloads). Each row hides one station for one winter and estimates it from its neighbors, as `/validate` does. Chill is counted Sept 1 to Feb 28. Hidden: Durham (12) for winters 2016-17 to 2024-25 (9) and Shafter (5) for 2016-17 to 2025-26 (10). Errors are estimate minus the station's own reading, in chill portions. Every row: `pitch/validation.csv`.

Lean = average error (positive: the estimate runs high). Typical miss = average size of the error. Worst = the largest miss. "Caps off" removes the 100 km and 300 m limits, but the walk still looks at the 30 closest stations only (`NEIGHBOR_CANDIDATES`).

## The 8 settings

| Setting | Complete | Typical miss, all 19 winters | Durham (12): lean / typical / worst / high-low | Shafter (5): lean / typical / worst / high-low |
|---|---|---|---|---|
| elevation on, 5 neighbors, caps on | yes | 4.01 | -1.4 / 2.9 / -8.1 / 3-6 | +4.8 / 5.0 / +10.6 / 9-1 |
| elevation on, 5 neighbors, caps off | no (2 station-seasons not saved: 277 in 2023-24, 277 in 2024-25) | 3.70 | -1.4 / 2.9 / -8.1 / 3-6 | +3.7 / 4.5 / +10.6 / 9-1 |
| elevation on, 3 neighbors, caps on | yes | 3.63 | -0.3 / 2.6 / -7.9 / 4-5 | +4.0 / 4.5 / +10.9 / 9-1 |
| elevation on, 3 neighbors, caps off | yes | 3.63 | -0.3 / 2.6 / -7.9 / 4-5 | +4.0 / 4.5 / +10.9 / 9-1 |
| elevation off, 5 neighbors, caps on | yes | 4.09 | -0.6 / 2.3 / -5.7 / 3-6 | +5.5 / 5.7 / +10.8 / 9-1 |
| elevation off, 5 neighbors, caps off | no (2 station-seasons not saved: 277 in 2023-24, 277 in 2024-25) | 4.31 | -0.6 / 2.3 / -5.7 / 3-6 | +5.5 / 6.1 / +10.8 / 9-1 |
| elevation off, 3 neighbors, caps on | yes | 3.52 | -1.0 / 2.4 / -8.8 / 4-5 | +3.9 / 4.5 / +10.4 / 9-1 |
| elevation off, 3 neighbors, caps off | yes | 3.52 | -1.0 / 2.4 / -8.8 / 4-5 | +3.9 / 4.5 / +10.4 / 9-1 |

## Recommended setting

**elevation off, 3 neighbors, caps on**: typical miss 3.52 chill portions over all 19 winters, against 4.01 for the setting before (elevation on, 5 neighbors, caps on).

Rule (Ada, Amendment D): complete settings only; lowest typical miss over all 19 winters; a tie with the previous setting at 1 decimal keeps the previous one; an exact tie goes to the setting with fewer changes.

Best for each demo on its own:
- Durham (12): elevation off, 5 neighbors, caps on (2.29).
- Shafter (5), the Kern pin: elevation off, 3 neighbors, caps on (4.49).

Picking the best of 8 settings on the same 19 winters slightly flatters the winner: its miss on new winters will likely be a little larger. At 3 neighbors with the same caps, elevation on gives 3.63, so the elevation adjustment makes no measurable difference here; most of the change comes from the number of neighbors.

## Kern: winters with Blackwells Corner (54) as a neighbor

Described only, not a conclusion (few winters each):
- elevation on, 5 neighbors, caps on: with 54: +6.6 over 5 winters; without 54: +3.1 over 5 winters.
- elevation off, 3 neighbors, caps on: without 54: +3.9 over 10 winters; station 54 is never one of the neighbors in this setting.

## Does Kern's high lean shrink?

- elevation on, 5 neighbors, caps on: lean +4.8, too high in 9 of 10 winters
- elevation on, 5 neighbors, caps off: lean +3.7, too high in 9 of 10 winters
- elevation on, 3 neighbors, caps on: lean +4.0, too high in 9 of 10 winters
- elevation on, 3 neighbors, caps off: lean +4.0, too high in 9 of 10 winters
- elevation off, 5 neighbors, caps on: lean +5.5, too high in 9 of 10 winters
- elevation off, 5 neighbors, caps off: lean +5.5, too high in 9 of 10 winters
- elevation off, 3 neighbors, caps on: lean +3.9, too high in 9 of 10 winters
- elevation off, 3 neighbors, caps off: lean +3.9, too high in 9 of 10 winters

## How sure: draft lines for Jina

From the shipped setting. "Usually within X" from the typical miss alone would overstate Kern: only about half its winters fall inside it. So each line says how many winters it is true for.
- Durham (12): "off by about 2 chill portions in a typical winter; within 2 in 6 of 9 winters" (typical miss 2.4; within 3 in 7, within 4 in 8).
- Shafter (5), the Kern pin: "off by about 4 chill portions in a typical winter; within 4 in 5 of 10 winters" (typical miss 4.5; within 5 in 6, within 6 in 6).

## Notes

- With 3 neighbors, `scripts/warm_cache.py` saves 3 stations per winter. On a fresh machine, the 5-neighbor rows need `NEIGHBORS=5 python scripts/warm_cache.py` first, or they show as incomplete.
- Synthetic data (`data.synthetic_temp`) also uses `LAPSE_F_PER_M`, so with 0 it has no elevation effect.

## Numbers for the pitch

- Durham (station 12 hidden, 9 winters): typical miss 2.4 chill portions, worst -8.8. (source: pitch/validation.csv, scripts/validation_table.py, shipped setting)
- Kern (Shafter hidden, 10 winters): lean +4.8 before, +3.9 with the shipped setting; too high in 9 of 10 winters. (source: pitch/validation.csv, scripts/validation_table.py)
- Shipped setting: elevation off, 3 neighbors, caps on. (source: pitch/validation.csv, scripts/validation_table.py, Ada's rule, Amendment D)
- 8 of the 10 nearest CIMIS stations to the Kern pin are listed as closed; 7 of them have no saved data in any winter since 2016-17. (source: CIMIS station list, data/cache/stations.parquet `active`, and the saved CIMIS data; computed by scripts/validation_table.py)
- Kern card for Feb 1, 2026 with Shafter's real data: pending (kern-real-station PR).
- Trend sentence for both demos: pending (history-trend PR).
- "Our chill matches FNRIC within X": pending (golden tests, B2).
