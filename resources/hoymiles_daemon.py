#!/usr/bin/env python3
"""Hoymiles Cloud daemon — pousse les données S-Miles vers Jeedom.

Architecture (validée 13/08/2026) :
- Burst m:0 + m:3 au rythme du serveur (dly ~1,5-3 s) : puissances temps réel
  (station + par micro/string). Push intelligent : seuil de changement.
- Polling lent count_station_real_data (60 s) : énergies jour/mois/total, CO2,
  statut, dernière donnée.
- Résilience : 3 échecs burst → mode dégradé polling seul ; backoff exponentiel ;
  refresh token (~2 h) et URI burst (~4 min).

Usage: hoymiles_daemon.py --config /tmp/jeedom/hoymilescloud/config.json
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hoymiles_api import HoymilesCloudApi, URI_REFRESH_MS, parse_day_data

PID_DIR = "/tmp/jeedom/hoymilescloud"


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


class HoymilesDaemon:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = {}
        self.config_mtime = 0
        self.api = None
        self.last_pushed = {}  # (eq, cmd) -> valeur
        self.uri = None
        self.uri_at = 0
        self.burst_failures = 0
        self.burst_ok = False
        self.micro_missing = {}  # sn -> cycles consécutifs sans réponse
        self.sid = None
        self.micros = []  # [sn, ...]
        self.micro_id_to_sn = {}  # id -> sn
        self.next_day_data = 0

    # ---------- Config / mapping ----------
    def load_config(self):
        mtime = os.path.getmtime(self.config_path)
        if mtime == self.config_mtime and self.config:
            return
        with open(self.config_path) as f:
            self.config = json.load(f)
        self.config_mtime = mtime
        self.mapping = self.config.get("mapping", {})
        log(f"Config chargée : {len(self.mapping)} équipement(s) mappé(s)")

    def cmd_id(self, eq_logical, cmd_logical):
        eq = self.mapping.get(eq_logical)
        if not eq:
            return None
        return eq.get("cmds", {}).get(cmd_logical)

    # ---------- Push Jeedom ----------
    def push(self, eq_logical, cmd_logical, value, threshold=None):
        cid = self.cmd_id(eq_logical, cmd_logical)
        if cid is None:
            return
        key = (eq_logical, cmd_logical)
        last = self.last_pushed.get(key)
        # Push intelligent : numérique → seuil ; autre → changement strict
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if last is not None:
                try:
                    if abs(float(value) - float(last)) < (threshold if threshold is not None else 0):
                        return
                except (TypeError, ValueError):
                    pass
        else:
            if last is not None and str(value) == str(last):
                return
        try:
            params = {"apikey": self.config["apikey"], "plugin": "hoymilescloud",
                      "type": "cmd", "id": cid, "value": value}
            url = self.config["jeedom_url"] + "/core/api/jeeApi.php?" + urllib.parse.urlencode(params)
            r = requests.get(url, timeout=10)
            if r.status_code == 200 and "Exception" not in r.text and "n'est pas autorisé" not in r.text:
                self.last_pushed[key] = value
            else:
                log(f"Push {eq_logical}/{cmd_logical}={value} rejeté (HTTP {r.status_code}): {r.text[:100]}")
        except Exception as e:
            log(f"Push {eq_logical}/{cmd_logical} échoué : {e}")

    # ---------- Boucles ----------
    def slow_poll(self):
        """count_station_real_data — énergies + statut."""
        try:
            d = self.api.get_realtime(self.sid)
            if not d:
                log("Slow poll : réponse vide de count_station_real_data (rate-limit silencieux ?) — nouvel essai au prochain cycle")
                return
            log(f"Slow poll OK : today_eq={d.get('today_eq')} last={d.get('last_data_time')}")
            t = self.config.get("delta_threshold", 1)
            st = f"station-{self.sid}"
            self.push(st, "real_power", d.get("real_power"), t)
            self.push(st, "today_eq", d.get("today_eq"), t)
            self.push(st, "month_eq", d.get("month_eq"), t)
            self.push(st, "total_eq", d.get("total_eq"), t)
            self.push(st, "year_eq", d.get("year_eq"), t)
            self.push(st, "self_rate", d.get("self_rate"), t)
            self.push(st, "co2", d.get("co2_emission_reduction"), t)
            self.push(st, "last_data_time", d.get("last_data_time", ""))
            self.push(st, "online", 1 if d.get("is_null") == 0 else 0)
            # statut alerte des micros (warn_data.warn via select_by_station)
            try:
                for m in self.api.get_micros(self.sid):
                    sn = m.get("sn")
                    if not sn:
                        continue
                    wd = m.get("warn_data") or {}
                    self.push(f"micro-{sn}", "warn", 1 if wd.get("warn") else 0)
            except Exception as e:
                log(f"warn micros échoué : {e}")
        except Exception as e:
            log(f"Slow poll échoué : {e}")

    def burst_poll(self):
        """Burst m:0 (station) + m:3 (micros) — puissances temps réel."""
        try:
            if not self.uri or (time.time() - self.uri_at) > URI_REFRESH_MS / 1000:
                self.uri = self.api.get_burst_uri(self.sid)
                self.uri_at = time.time()
                log("URI burst rafraîchie")
            if not self.uri:
                raise RuntimeError("Pas d'URI burst")

            t = self.config.get("delta_threshold", 1)
            dly = 1500
            # m:0 — station
            code, resp = self.api.burst(self.uri, mode=0)
            if resp.get("status") == "0":
                data = resp.get("data") or {}
                dly = data.get("dly", dly)
                power = data.get("power") or {}
                st = f"station-{self.sid}"
                if power.get("pv") is not None:
                    self.push(st, "real_power", power["pv"], t)
                if power.get("pvr") is not None:
                    self.push(st, "self_rate", power["pvr"], t)
            else:
                raise RuntimeError(f"burst m:0 → {resp.get('status')} {resp.get('message')}")

            # m:3 — micros
            if self.micros:
                code, resp = self.api.burst(self.uri, mode=3, mis=self.micros)
                if resp.get("status") == "0":
                    data = resp.get("data") or {}
                    dly = data.get("dly", dly)
                    seen = set()
                    for mi in data.get("mis", []):
                        sn = mi.get("sn")
                        if not sn:
                            continue
                        seen.add(sn)
                        self.micro_missing[sn] = 0
                        eq = f"micro-{sn}"
                        self.push(eq, "pac", mi.get("pac"), t)
                        for p in (1, 2, 3, 4):
                            self.push(eq, f"p{p}", mi.get(f"p{p}"), t)
                        self.push(eq, "connect", 1)
                    for sn in self.micros:
                        if sn not in seen:
                            self.micro_missing[sn] = self.micro_missing.get(sn, 0) + 1
                            if self.micro_missing[sn] >= 5:
                                self.push(f"micro-{sn}", "connect", 0)
                    self.burst_ok = True
                    self.burst_failures = 0
                else:
                    raise RuntimeError(f"burst m:3 → {resp.get('status')} {resp.get('message')}")
            return dly
        except Exception as e:
            self.burst_failures += 1
            log(f"Burst échec #{self.burst_failures} : {e}")
            if self.burst_failures >= 3:
                log("3 échecs burst — mode dégradé (polling seul)")
                self.burst_ok = False
            return 30000

    def day_data_poll(self):
        """down_module_day_data (protobuf) toutes les 5 min — tension réseau,
        fréquence, température interne du micro et tension/courant DC par port
        (dernier bucket 5 min, grain identique à l'app S-Miles)."""
        try:
            blob = self.api.get_day_data(self.sid, time.strftime("%Y-%m-%d"))
            if not blob:
                log("Day data : réponse vide/refusée — nouvel essai au prochain cycle")
                return
            data = parse_day_data(blob)
            t = 0.1  # seuil serré : ces valeurs bougent peu entre 2 buckets
            for mid, entry in data.get("micros", {}).items():
                sn = self.micro_id_to_sn.get(mid)
                if not sn:
                    continue
                eq = f"micro-{sn}"
                for cmd, val in (("uac", entry.get("uac")), ("freq", entry.get("freq")),
                                 ("temp", entry.get("temp"))):
                    if val is not None:
                        self.push(eq, cmd, round(val, 2), t)
                for port, p in entry.get("ports", {}).items():
                    if port not in (1, 2):
                        continue
                    if p.get("up") is not None:
                        self.push(eq, f"up{port}", round(p["up"], 1), t)
                    if p.get("ip") is not None:
                        self.push(eq, f"ip{port}", round(p["ip"], 2), t)
            log(f"Day data OK : {len(data.get('micros', {}))} micro(s) — "
                f"uac/temp/up/ip mis à jour")
        except Exception as e:
            log(f"Day data échoué : {e}")

    # ---------- Boucle principale ----------
    def run(self):
        log("Démarrage du démon Hoymiles Cloud")
        self.load_config()
        self.api = HoymilesCloudApi(self.config["user"], self.config["password"],
                                    profile=self.config.get("profile", "auto"))
        self.api.ensure_token()
        log(f"Login OK ({self.api.method})")

        stations = self.api.get_stations()
        if not stations:
            log("Aucune station — attente de config")
        self.sid = stations[0]["id"] if stations else None
        if self.sid:
            micros = self.api.get_micros(self.sid)
            self.micros = [m["sn"] for m in micros]
            self.micro_id_to_sn = {m["id"]: m["sn"] for m in micros if m.get("id")}
            log(f"Station {self.sid} — {len(self.micros)} micro(s): {self.micros}")
        else:
            self.micros = []

        burst_interval = max(2, int(self.config.get("burst_interval", 2)))
        slow_interval = max(15, int(self.config.get("slow_interval", 60)))

        # pid file
        os.makedirs(PID_DIR, exist_ok=True)
        with open(PID_DIR + "/daemon.pid", "w") as f:
            f.write(str(os.getpid()))

        next_slow = time.time()
        next_uri_check = 0
        next_day_data = time.time() + 30  # 1er fetch 30 s après démarrage
        while True:
            try:
                self.load_config()  # recharge si resync côté Jeedom
                if not self.sid:
                    stations = self.api.get_stations()
                    if stations:
                        self.sid = stations[0]["id"]
                if time.time() >= next_slow:
                    if self.sid:
                        self.slow_poll()
                    next_slow = time.time() + slow_interval

                if self.sid and time.time() >= next_day_data:
                    self.day_data_poll()
                    next_day_data = time.time() + max(300, int(self.config.get("day_data_interval", 300)))

                if self.burst_ok or self.burst_failures < 3:
                    dly = 10000
                    if self.sid:
                        dly = self.burst_poll()
                    time.sleep(max(dly, burst_interval * 1000) / 1000)
                else:
                    time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"Erreur boucle : {e}")
                time.sleep(10)
        log("Arrêt du démon")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    HoymilesDaemon(args.config).run()
