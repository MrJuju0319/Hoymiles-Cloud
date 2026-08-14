#!/usr/bin/env python3
"""Backfill historique : récupère les 15 derniers jours de séries complètes
(up/ip/watt/énergie par port + uac/freq/temp) pour chaque micro et écrit
un JSON d'ingestion pour le plugin Jeedom (PHP backfillHistory).

Usage : .venv/bin/python backfill.py [jours]   (défaut 15, max 15)
Sortie : backfill.json dans le même dossier (à copier dans le tmp du plugin).
"""
import json
import os
import struct
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plugin.hoymilescloud.resources.hoymiles_api import (
    HoymilesCloudApi, _pb_parse, _pb_f32,
)

SID = 14862230
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backfill.json")


def parse_day_series(blob):
    """Séries COMPLÈTES par micro : times + ports (up/ip/watt/e) + AC (uac/freq/temp).
    Retourne {micro_id: {times, ports: {port: {up:[],ip:[],watt:[],e:[]}}, uac:[], freq:[], temp:[]}}"""
    result = {}
    for f, w, v in _pb_parse(blob):
        if not (f == 3 and w == 2):
            continue
        sub = _pb_parse(v)
        mid = next((x[2] for x in sub if x[0] == 1 and x[1] == 0), None)
        main = next((x[2] for x in sub if x[0] == 2 and x[1] == 2), b"")
        if mid is None:
            continue
        times = []
        ports = {}
        ac = {}
        for mf, mw, mv in _pb_parse(main):
            if mf == 2 and mw == 2:
                s = mv.decode(errors="ignore")
                if ":" in s and "-" not in s and len(s) == 5:
                    times.append(s)
            elif mf == 4 and mw == 2:
                # port msg : field 1 varint = port, field 2 = batch de points
                # (batch : field 1 repeated = points ; point : fixed32 1=up 2=ip 3=watt 4=énergie)
                port = None
                pts = []
                for pf, pw, pv in _pb_parse(mv):
                    if pf == 1 and pw == 0:
                        port = pv
                    elif pf == 2 and pw == 2:
                        for qf, qw, qv in _pb_parse(pv):
                            if qf == 1 and qw == 2:
                                vals = {}
                                for rf, rw, rv in _pb_parse(qv):
                                    if rw == 5 and rf in (1, 2, 3, 4):
                                        vals[rf] = _pb_f32(rv)
                                if vals:
                                    pts.append(vals)
                if port is not None and pts:
                    series = {"up": [], "ip": [], "watt": [], "e": []}
                    for p in pts:
                        series["up"].append(p.get(1))
                        series["ip"].append(p.get(2))
                        series["watt"].append(p.get(3))
                        series["e"].append(p.get(4))
                    ports[port] = series
            elif mf in (5, 6, 7) and mw == 2:
                n = len(mv) // 4
                ac[mf] = list(struct.unpack(f"<{n}f", mv))
        if times:
            result[mid] = {"times": times, "ports": ports,
                           "uac": ac.get(7), "freq": ac.get(5), "temp": ac.get(6)}
    return result


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    days = max(1, min(days, 15))
    env = {}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    api = HoymilesCloudApi(env["HOYMILES_USER"], env["HOYMILES_PASS"])
    api.ensure_token()
    print(f"[auth] OK ({api.method})")

    micros = api.get_micros(SID)
    id2sn = {m["id"]: m["sn"] for m in micros if m.get("id") and m.get("sn")}
    print(f"[micros] {len(id2sn)} → {id2sn}")

    # {eq_logical: {cmd_logical: [[datetime, value], ...]}}
    out = {}
    today = date.today()
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        blob = api.get_day_data(SID, day.isoformat())
        if not blob:
            print(f"  {day} : pas de données")
            continue
        series = parse_day_series(blob)
        if not series:
            print(f"  {day} : protobuf vide")
            continue
        for mid, s in series.items():
            sn = id2sn.get(mid)
            if not sn:
                continue
            eq = f"micro-{sn}"
            out.setdefault(eq, {})
            n = len(s["times"])
            # séries par port : alignées sur times (même longueur)
            for port, ser in s["ports"].items():
                if port not in (1, 2):
                    continue
                for cmd, key in (("up", "up"), ("ip", "ip"), ("p", "watt"), ("e", "e")):
                    vals = ser[key]
                    if not vals:
                        continue
                    lst = out[eq].setdefault(f"{cmd}{port}", [])
                    for t, v in zip(s["times"], vals):
                        if v is None:
                            continue
                        lst.append([f"{day} {t}:00", round(v, 3)])
            # séries AC par micro
            for cmd, key in (("uac", "uac"), ("freq", "freq"), ("temp", "temp")):
                vals = s[key]
                if not vals:
                    continue
                lst = out[eq].setdefault(cmd, [])
                for t, v in zip(s["times"], vals):
                    lst.append([f"{day} {t}:00", round(v, 3)])
        print(f"  {day} : {len(series)} micro(s) OK")

    total = sum(len(v) for eq in out.values() for v in eq.values())
    print(f"\nTotal : {total} points pour {len(out)} équipement(s)")
    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"Écrit : {OUT} ({os.path.getsize(OUT)} octets)")


if __name__ == "__main__":
    main()
