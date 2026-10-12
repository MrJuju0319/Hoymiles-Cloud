"""Tests des parseurs protobuf (day_data) — parseur « dernier bucket » du démon
et parseur « séries complètes » du backfill.

Fixtures : blob construit par tests/pbgen.py (aucun accès réseau, aucune
capture réelle embarquée dans le dépôt).
"""
from datetime import date

import pytest

import pbgen
from backfill import parse_day_series
from hoymiles_api import parse_day_data

SID = 14862230
DAY = "2026-10-12"
TIMES = ["17:05", "17:10", "17:15"]

MICRO_2P = pbgen.micro_msg(
    micro_id=34457860,
    times=TIMES,
    ports={
        1: [pbgen.point(230.1, 5.20, 1000.0, 700.0),
            pbgen.point(230.2, 5.30, 1010.0, 710.0),
            pbgen.point(230.3, 5.40, 1020.0, 720.0)],
        2: [pbgen.point(228.5, 5.10, 980.0, 690.0),
            pbgen.point(228.6, 5.15, 985.0, 700.0),
            pbgen.point(228.7, 5.20, 990.0, 705.0)],
    },
    freq=[50.00, 50.01, 50.02],
    temp=[41.5, 41.8, 42.0],
    uac=[231.0, 231.2, 231.5],
    alarms=[0, 0, 6],
)

MICRO_4P = pbgen.micro_msg(
    micro_id=34469900,
    times=TIMES,
    ports={
        3: [pbgen.point(220.0, 4.0, 300.0, 100.0),
            pbgen.point(221.0, 4.1, 310.0, 105.0),
            pbgen.point(222.0, 4.2, 320.0, 110.0)],
        4: [pbgen.point(219.0, 4.5, 290.0, 90.0),
            pbgen.point(219.5, 4.6, 295.0, 95.0),
            pbgen.point(219.9, 4.7, 299.0, 99.0)],
    },
    freq=[50.00, 50.00, 49.99],
    temp=[38.0, 38.4, 38.8],
    uac=[230.0, 230.1, 230.2],
)

BLOB = pbgen.day_blob(SID, DAY, [MICRO_2P, MICRO_4P])


# ---------- parse_day_data (démon : dernier bucket) ----------
def test_parse_day_data_entete():
    data = parse_day_data(BLOB)
    assert data["sid"] == SID
    assert data["date"] == DAY


def test_parse_day_data_dernier_bucket_ac_par_micro():
    data = parse_day_data(BLOB)
    m = data["micros"][34457860]
    assert m["freq"] == pytest.approx(50.02, abs=0.01)
    assert m["temp"] == pytest.approx(42.0, abs=0.01)
    assert m["uac"] == pytest.approx(231.5, abs=0.01)
    assert m["times"] == TIMES


def test_parse_day_data_ports_du_dernier_bucket():
    data = parse_day_data(BLOB)
    m = data["micros"][34457860]
    assert m["ports"][1]["up"] == pytest.approx(230.3, abs=0.01)
    assert m["ports"][1]["ip"] == pytest.approx(5.40, abs=0.01)
    assert m["ports"][1]["p"] == pytest.approx(1020.0, abs=0.1)
    assert m["ports"][1]["e"] == pytest.approx(720.0, abs=0.1)
    assert m["ports"][2]["e"] == pytest.approx(705.0, abs=0.1)


def test_parse_day_data_alarmes_deduplicuees():
    """Champ 8 = série int16 par bucket ; 0 = pas d'alarme."""
    data = parse_day_data(BLOB)
    assert data["micros"][34457860]["alarm_codes"] == [6]
    assert data["micros"][34469900]["alarm_codes"] == []


def test_parse_day_data_micro_4_ports_non_tronque():
    """Régression : le parseur du démon ne doit pas limiter aux ports 1-2."""
    data = parse_day_data(BLOB)
    assert sorted(data["micros"][34469900]["ports"].keys()) == [3, 4]


# ---------- parse_day_series (backfill : séries complètes) ----------
def test_parse_day_series_series_completes():
    series = parse_day_series(BLOB)
    m = series[34457860]
    assert len(m["times"]) == 3
    assert len(m["ports"][1]["up"]) == 3
    assert m["ports"][1]["watt"] == pytest.approx([1000.0, 1010.0, 1020.0], abs=0.1)
    assert m["ports"][1]["e"] == pytest.approx([700.0, 710.0, 720.0], abs=0.1)
    assert m["uac"] == pytest.approx([231.0, 231.2, 231.5], abs=0.01)
    assert m["temp"][-1] == pytest.approx(42.0, abs=0.01)


def test_parse_day_series_quatre_ports():
    series = parse_day_series(BLOB)
    assert sorted(series[34469900]["ports"].keys()) == [3, 4]


def test_parse_day_series_blob_vide():
    assert parse_day_series(b"") == {}
    assert parse_day_data(b"")["micros"] == {}


# ---------- Cas dégradés ----------
def test_point_sans_energie_ne_casse_pas_le_parseur():
    """Un bucket sans champ 4 (énergie) doit rester lisible (e = None)."""
    micro = pbgen.micro_msg(1, TIMES, {1: [pbgen.point(230.0, 5.0, 500.0)]})
    blob = pbgen.day_blob(SID, DAY, [micro])
    data = parse_day_data(blob)
    assert data["micros"][1]["ports"][1]["p"] == pytest.approx(500.0, abs=0.1)
    assert data["micros"][1]["ports"][1]["e"] is None
