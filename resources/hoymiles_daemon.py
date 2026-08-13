#!/usr/bin/env python3
"""Hoymiles Cloud daemon — pousse les données S-Miles vers Jeedom.

Architecture v0.1.5 (validée 13/08/2026) — threads + file d'attente :

- 3 threads COLLECTEURS indépendants (un blocage réseau ne fige jamais les autres) :
    * burst   : m:0 + m:3 au rythme du serveur (dly ~1,5-3 s) — puissances temps réel
    * slow    : count_station_real_data toutes les 60 s — énergies, statut, heartbeat
    * day     : down_module_day_data toutes les 5 min — tensions/courants/températures
- 1 thread PUSHER : consomme une file d'attente (queue.Queue) et fait les requêtes
  HTTP vers Jeedom de façon séquentielle (timeout strict 10 s).
- Timeouts stricts partout (API ≤ 10 s, day_data 15 s, push 10 s) : un blocage
  réseau = un appel échoué, jamais un démon figé.
- Aucune écriture disque en fonctionnement normal (important carte SD Raspberry Pi) :
  le pid file est écrit 1× au démarrage, la config est relue depuis /tmp (écrite par
  Jeedom), et status.json n'est écrit QUE lors d'un CHANGEMENT d'état (rare).
- Heartbeat : commande `daemon` (station) poussée en FORCE toutes les 60 s → un
  scénario Jeedom peut alerter si la commande n'est plus mise à jour depuis X min.
- Auto-refresh token : tout appel répondant status=100 (token expiré) déclenche un
  re-login + retry, sans redémarrage (verrouillé par lock : pas de double login).

Usage: hoymiles_daemon.py --config /tmp/jeedom/hoymilescloud/config.json
"""
import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.parse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hoymiles_api import HoymilesCloudApi, URI_REFRESH_MS, parse_day_data

PID_DIR = "/tmp/jeedom/hoymilescloud"
STATUS_FILE = PID_DIR + "/status.json"
PUSH_TIMEOUT = 10      # timeout strict des push Jeedom
HEARTBEAT_CMD = "daemon"  # commande binaire de santé, poussée en force


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


class HoymilesDaemon:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = {}
        self.config_mtime = 0
        self.config_last_check = 0
        self.api = None
        self.last_pushed = {}   # (eq, cmd) -> valeur — cache EN MÉMOIRE (aucun FS)
        self.uri = None
        self.uri_at = 0
        self.burst_failures = 0
        self.burst_ok = False
        self.slow_failures = 0
        self.micro_missing = {}  # sn -> cycles consécutifs sans réponse
        self.sid = None
        self.micros = []  # [sn, ...]
        self.micro_id_to_sn = {}  # id -> sn

        # file d'attente + threads
        self.q = queue.Queue(maxsize=2000)
        self.stop_event = threading.Event()
        self.push_lock = threading.Lock()
        self.threads = []

        # état publié (status.json) — écrit uniquement sur changement
        self.status = {
            "state": "starting", "ts": time.time(), "error": None,
            "burst_ok": False, "slow_ok": False, "day_ok": False,
            "last_data": None, "degraded_since": None,
        }
        self._status_sig = None

    # ---------- Config / mapping ----------
    def load_config(self):
        """Relecture de la config écrite par Jeedom — au plus toutes les 5 s
        (un stat() par cycle sur /tmp est sans impact, mais restons frugal)."""
        now = time.time()
        if now - self.config_last_check < 5 and self.config:
            return
        self.config_last_check = now
        try:
            mtime = os.path.getmtime(self.config_path)
        except OSError:
            return
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

    # ---------- État publié (status.json, écriture seulement sur changement) ----------
    def _set_status(self, **kw):
        self.status.update(kw)
        self.status["ts"] = time.time()
        sig = (self.status["state"], self.status["burst_ok"], self.status["slow_ok"],
               self.status["day_ok"], self.status["last_data"], self.status["error"])
        if sig == self._status_sig:
            return  # rien n'a changé → zéro écriture disque
        self._status_sig = sig
        try:
            os.makedirs(PID_DIR, exist_ok=True)
            tmp = STATUS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.status, f)
            os.replace(tmp, STATUS_FILE)  # atomique
        except Exception as e:
            log(f"status.json : {e}")

    # ---------- Push Jeedom (file d'attente, non bloquant) ----------
    def push(self, eq_logical, cmd_logical, value, threshold=None, force=False):
        """Mise en file — le thread pusher s'occupe du HTTP (timeout strict).
        force=True (heartbeat) : contourne le push intelligent."""
        self.q.put((eq_logical, cmd_logical, value, threshold, force))

    def _do_push(self, eq_logical, cmd_logical, value, threshold, force):
        cid = self.cmd_id(eq_logical, cmd_logical)
        if cid is None:
            return
        key = (eq_logical, cmd_logical)
        with self.push_lock:
            last = self.last_pushed.get(key)
            # Push intelligent : numérique → seuil ; autre → changement strict
            if not force:
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
            r = requests.get(url, timeout=PUSH_TIMEOUT)
            if r.status_code == 200 and "Exception" not in r.text and "n'est pas autorisé" not in r.text:
                with self.push_lock:
                    self.last_pushed[key] = value
            else:
                log(f"Push {eq_logical}/{cmd_logical}={value} rejeté (HTTP {r.status_code}): {r.text[:100]}")
        except Exception as e:
            log(f"Push {eq_logical}/{cmd_logical} échoué : {e}")

    def _push_loop(self):
        """Consomme la file — un push bloqué ne retarde que les autres push."""
        while not self.stop_event.is_set():
            try:
                item = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._do_push(*item)
            except Exception as e:
                log(f"Push exception : {e}")

    # ---------- Boucle burst (temps réel) ----------
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
                    self._set_status(burst_ok=True, error=None)
                else:
                    raise RuntimeError(f"burst m:3 → {resp.get('status')} {resp.get('message')}")
            return dly
        except Exception as e:
            self.burst_failures += 1
            log(f"Burst échec #{self.burst_failures} : {e}")
            if self.burst_failures >= 3:
                log("3 échecs burst — mode dégradé (polling seul)")
                self.burst_ok = False
                self._set_status(burst_ok=False, error=str(e)[:120])
            return 30000

    def _burst_loop(self):
        while not self.stop_event.is_set():
            try:
                dly = 10000
                if self.sid:
                    dly = self.burst_poll()
                self.stop_event.wait(max(dly, 2000) / 1000)
            except Exception as e:
                log(f"Burst loop : {e}")
                self.stop_event.wait(5)

    # ---------- Boucle lente (énergies + statut + heartbeat) ----------
    def slow_poll(self):
        """count_station_real_data — énergies + statut + heartbeat démon."""
        try:
            d = self.api.get_realtime(self.sid)
            if not d:
                self.slow_failures += 1
                log("Slow poll : réponse vide de count_station_real_data (rate-limit silencieux ?) — nouvel essai au prochain cycle")
                if self.slow_failures >= 3:
                    self._set_status(slow_ok=False, error="slow poll vide x3 (rate-limit ?)")
                return
            self.slow_failures = 0
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
            # heartbeat santé du démon — FORCÉ (contourne le push intelligent) :
            # la commande `daemon` est mise à jour toutes les 60 s ; un scénario
            # peut alerter si elle n'est plus mise à jour depuis X minutes.
            self.push(st, HEARTBEAT_CMD, 1, force=True)
            self._set_status(slow_ok=True, last_data=d.get("last_data_time"), error=None)
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
            self.slow_failures += 1
            log(f"Slow poll échoué : {e}")
            if self.slow_failures >= 3:
                self._set_status(slow_ok=False, error=str(e)[:120])

    def _slow_loop(self):
        interval = 60
        while not self.stop_event.is_set():
            try:
                self.load_config()
                interval = max(15, int(self.config.get("slow_interval", 60)))
                if self.sid:
                    self.slow_poll()
            except Exception as e:
                log(f"Slow loop : {e}")
            self.stop_event.wait(interval)

    # ---------- Boucle données jour (tensions/courants/températures) ----------
    def day_data_poll(self):
        """down_module_day_data (protobuf) — tension réseau, fréquence,
        température interne du micro et tension/courant DC par port
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
            self._set_status(day_ok=True, error=None)
            log(f"Day data OK : {len(data.get('micros', {}))} micro(s) — uac/temp/up/ip mis à jour")
        except Exception as e:
            log(f"Day data échoué : {e}")
            self._set_status(day_ok=False, error=str(e)[:120])

    def _day_loop(self):
        interval = 300
        while not self.stop_event.is_set():
            try:
                self.load_config()
                interval = max(300, int(self.config.get("day_data_interval", 300)))
                if self.sid:
                    self.day_data_poll()
            except Exception as e:
                log(f"Day loop : {e}")
            self.stop_event.wait(interval)

    # ---------- Démarrage ----------
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

        # pid file (1 seule écriture au démarrage)
        os.makedirs(PID_DIR, exist_ok=True)
        with open(PID_DIR + "/daemon.pid", "w") as f:
            f.write(str(os.getpid()))

        self._set_status(state="ok")

        # 4 threads : 3 collecteurs + 1 pusher
        targets = [self._burst_loop, self._slow_loop, self._day_loop, self._push_loop]
        self.threads = [threading.Thread(target=t, daemon=True, name=t.__name__) for t in targets]
        for th in self.threads:
            th.start()
        log("Threads démarrés : burst, slow, day_data, push")

        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(5)
        except KeyboardInterrupt:
            log("Arrêt demandé")
        finally:
            self.stop_event.set()
            self.q.put(None)  # débloque le pusher
            self._set_status(state="stopped")
            for th in self.threads:
                th.join(timeout=3)
        log("Arrêt du démon")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    HoymilesDaemon(args.config).run()
