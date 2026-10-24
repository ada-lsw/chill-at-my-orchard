"""data.get_stations reads the station list once per process, and again only if the file changes."""
import os

import pandas as pd
import pytest

from app import config, data


@pytest.fixture
def saved_list(tmp_path, monkeypatch):
    """Real-data mode with a scratch cache holding a two-station list; counts parquet reads."""
    monkeypatch.setattr(config, "DATA_SOURCE", "cimis")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    data._synthetic_stations().head(2).to_parquet(tmp_path / "stations.parquet")
    reads = []
    real = pd.read_parquet
    monkeypatch.setattr(data.pd, "read_parquet", lambda path, *a, **k: reads.append(path) or real(path, *a, **k))
    return tmp_path, reads


def test_station_list_is_read_once(saved_list):
    _, reads = saved_list
    for _ in range(3):
        stations = data.get_stations()
    assert len(stations) == 2 and len(reads) == 1


def test_a_changed_station_list_is_read_again(saved_list):
    """Guard test: rewriting the file (new time and size) gives the new list."""
    folder, _ = saved_list
    data.get_stations()
    path = folder / "stations.parquet"
    data._synthetic_stations().head(3).to_parquet(path)
    later = path.stat().st_mtime + 5
    os.utime(path, (later, later))
    assert len(data.get_stations()) == 3


def test_callers_cannot_change_the_saved_list(saved_list):
    """Each caller gets its own copy, so changing it can't affect the next caller."""
    first = data.get_stations()
    first["name"] = "changed"
    assert "changed" not in set(data.get_stations()["name"])
