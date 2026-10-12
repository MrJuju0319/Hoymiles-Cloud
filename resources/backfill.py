#!/usr/bin/env python3
"""Backfill historique : récupère les 15 derniers jours de séries complètes
(up/ip/watt/énergie par port + uac/freq/temp) pour chaque micro et écrit un JSON
d'ingestion pour le plugin Jeedom (PHP hoymilescloud::backfillHistory).

Le plugin l'appelle depuis la page de configuration (bouton « Récupérer
l'historique (15 jours) ») avec un fichier d'authentification 0600 :

    python backfill.py --config /tmp/jeedom/hoymilescloud/backfill_auth.json

Le fichier de configuration contient : user, password, sid (optionnel),
days (optionnel, 15 max) et out (chemin du JSON produit).

Utilisation manuelle équivalente :

    HOYMILES_USER=... HOYMILES_PASS=... python backfill.py [jours] [--out fichier]

Les identifiants ne passent JAMAIS en argument de ligne de commande (visibles
dans `ps`).
"""
import argparse
import json
import os
import struct
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hoymiles_api import HoymilesCloudApi, _pb_parse, _pb_f32

# L'API cloud n'expose que 15 jours d'historique par micro
MAX_DAYS = 15


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


def read_env_file(path):
    """Ancien mode : fichier .env (dev) — conservé pour les lancements manuels."""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def load_settings(args):
    """Résolution des identifiants : --config (plugin) > variables
    d'environnement > fichier .env local (dev)."""
    settings = {"user": "", "password": "", "sid": "", "days": MAX_DAYS, "out": ""}
    if args.config:
        with open(args.config) as f:
            settings.update({k: v for k, v in json.load(f).items() if v is not None})
    env = read_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    settings["user"] = settings.get("user") or os.environ.get("HOYMILES_USER") or env.get("HOYMILES_USER", "")
    settings["password"] = settings.get("password") or os.environ.get("HOYMILES_PASS") or env.get("HOYMILES_PASS", "")
    settings["sid"] = settings.get("sid") or os.environ.get("HOYMILES_SID") or env.get("HOYMILES_SID", "")
    if args.days:
        settings["days"] = args.days
    if args.out:
        settings["out"] = args.out
    settings["days"] = max(1, min(int(settings.get("days") or MAX_DAYS), MAX_DAYS))
    settings["out"] = settings.get("out") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "backfill.json")
    if not settings["user"] or not settings["password"]:
        raise SystemExit("Identifiants S-Miles absents (--config, HOYMILES_USER/HOYMILES_PASS ou .env)")
    return settings


def main():
    ap = argparse.ArgumentParser(description="Backfill historique Hoymiles Cloud")
    ap.add_argument("days", nargs="?", type=int, help="nombre de jours (1 à 15)")
    ap.add_argument("--config", help="fichier JSON {user, password, sid, days, out} (écrit par le plugin)")
    ap.add_argument("--out", help="chemin du JSON à produire")
    args = ap.parse_args()

    settings = load_settings(args)
    # Le fichier d'authentification (écrit par le plugin, contenant le mot de
    # passe) est supprimé dès qu'il a été lu : il ne doit pas traîner dans /tmp.
    if args.config:
        try:
            os.unlink(args.config)
        except OSError:
            pass
    api = HoymilesCloudApi(settings["user"], settings["password"])
    api.ensure_token()
    print(f"[auth] OK ({api.method})")

    # Station : celle fournie (sid du plugin) ou la première du compte
    sid = settings["sid"]
    if not sid:
        stations = api.get_stations()
        if not stations:
            raise SystemExit("Aucune station sur ce compte S-Miles")
        sid = stations[0]["id"]
    print(f"[station] {sid}")

    micros = api.get_micros(sid)
    id2sn = {m["id"]: m["sn"] for m in micros if m.get("id") and m.get("sn")}
    print(f"[micros] {len(id2sn)} → {id2sn}")

    # {eq_logical: {cmd_logical: [[datetime, value], ...]}}
    out = {}
    today = date.today()
    for i in range(settings["days"], 0, -1):
        day = today - timedelta(days=i)
        blob = api.get_day_data(sid, day.isoformat())
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
            # Séries par port : tous les ports présents dans les données
            # (2 MPPT ou 4 MPPT — plus de filtre sur (1, 2)).
            for port, ser in s["ports"].items():
                for cmd, key in (("up", "up"), ("ip", "ip"), ("p", "watt"), ("e", "e")):
                    vals = ser[key]
                    if not vals:
                        continue
                    lst = out[eq].setdefault(f"{cmd}{port}", [])
                    for t, v in zip(s["times"], vals):
                        if v is None:
                            continue
                        lst.append([f"{day} {t}:00", round(v, 3)])
            # Séries AC par micro
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
    os.makedirs(os.path.dirname(settings["out"]), exist_ok=True)
    with open(settings["out"], "w") as f:
        json.dump(out, f)
    print(f"Écrit : {settings['out']} ({os.path.getsize(settings['out'])} octets)")


if __name__ == "__main__":
    main()
