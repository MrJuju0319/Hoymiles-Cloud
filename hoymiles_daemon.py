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
- Zeroing hors ligne (v0.1.8) : micro hors ligne (flag cloud `connect`) depuis plus
  de OFF_LINE_DELAY (300 s) → valeurs électriques (V/A/W/Hz) forcées à 0
  (comportement "pleine nuit") : aucun scénario ne voit une valeur figée d'un
  micro déconnecté. La température interne reste à sa dernière valeur connue.

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
from hoymiles_api import (HoymilesCloudApi, URI_REFRESH_MS, parse_day_data,
                          jeedom_decrypt, ALARM_MESSAGES)

PID_DIR = "/tmp/jeedom/hoymilescloud"
STATUS_FILE = PID_DIR + "/status.json"
PUSH_TIMEOUT = 10      # timeout strict des push Jeedom
HEARTBEAT_CMD = "daemon"  # commande binaire de santé, poussée en force

# Zeroing micro hors ligne (v0.1.8) : après ce délai (s) sans `connect` cloud,
# les commandes électriques du micro sont forcées à 0 (comportement nuit).
OFF_LINE_DELAY = 300
# Commandes électriques concernées : tensions (V), courants (A), production (W),
# fréquence (Hz). `temp` est volontairement exclue (valeur thermique : en pleine
# nuit la température interne du micro ne tomberait pas à 0).
ELECTRICAL_CMDS = {"uac", "up1", "up2", "ip1", "ip2", "freq", "pac",
                   "p1", "p2", "p3", "p4"}


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
        self._last_no_uri_log = 0  # log espacé "pas d'URI burst" (1×/10 min)
        self.slow_failures = 0
        self.micro_missing = {}  # sn -> cycles consécutifs sans réponse
        self.alarm_codes = {}    # sn -> [codes d'alarme] (du protobuf day_data)
        self.offline_since = {}  # sn -> ts du passage hors ligne (flag cloud connect)
        self.zero_logged = set()  # sn dont le zeroing a déjà été loggué
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
        # Sécurité : le mot de passe S-Miles est stocké chiffré (crypt:...) dans le
        # fichier runtime — déchiffrement avec la clé Jeedom avant utilisation.
        # Jamais loggé, jamais réécrit en clair.
        if self.config.get("password", "").startswith("crypt:"):
            root = self.config.get("jeedom_root", "/var/www/html")
            try:
                self.config["password"] = jeedom_decrypt(self.config["password"], root)
            except Exception as e:
                log(f"ERREUR config : {e}")
                self.config["password"] = ""
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
    def _offline_zero(self, eq_logical, cmd_logical):
        """True si la valeur doit être forcée à 0 : micro hors ligne (flag cloud
        `connect` — même source que le statut "Alerte") depuis plus de
        OFF_LINE_DELAY, sur une commande électrique (V/A/W/Hz).
        Station : real_power forcée à 0 seulement si TOUS les micros sont
        hors ligne (sinon on masquerait la production des micros sains)."""
        if eq_logical.startswith("station-"):
            # real_power (production station) : zéro seulement si TOUS les micros
            # sont hors ligne depuis OFF_LINE_DELAY (sinon on masquerait la
            # production des micros sains). Les autres commandes station ne sont
            # jamais zéroées (énergies cumulées, %, co2…).
            if cmd_logical == "real_power" and self.micros:
                now = time.time()
                return all(s in self.offline_since and
                           (now - self.offline_since[s]) >= OFF_LINE_DELAY
                           for s in self.micros)
            return False
        if cmd_logical not in ELECTRICAL_CMDS:
            return False
        if eq_logical.startswith("micro-"):
            sn = eq_logical[len("micro-"):]
            since = self.offline_since.get(sn)
            return since is not None and (time.time() - since) >= OFF_LINE_DELAY
        return False

    def push(self, eq_logical, cmd_logical, value, threshold=None, force=False):
        """Mise en file — le thread pusher s'occupe du HTTP (timeout strict).
        force=True (heartbeat) : contourne le push intelligent.
        Micro hors ligne > OFF_LINE_DELAY : les valeurs électriques sont
        remplacées par 0 avant mise en file (aucune valeur figée remontée)."""
        if value is not None and self._offline_zero(eq_logical, cmd_logical):
            value = 0
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
                if self.uri:
                    log("URI burst rafraîchie")
            if not self.uri:
                # Pas d'URI burst = la station ne produit pas (nuit) ou le cloud
                # n'expose pas de flux temps réel. Ce n'est PAS une panne : le
                # polling lent (slow 60 s + day 5 min) continue de tourner. Log
                # espacé (1×/10 min) et nouvel essai dans 5 min (zéro rate-limit).
                if time.time() - self._last_no_uri_log > 600:
                    self._last_no_uri_log = time.time()
                    log("Aucune URI burst (station en veille la nuit ?) — "
                        "polling lent seul, nouvel essai dans 5 min")
                return 300000

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

    # ---------- Santé micros ----------
    def _alarm_status(self, warn, connect, codes):
        """Traduit l'état brut S-Miles en 3 statuts lisibles pour Jeedom.

        Logique de sévérité (simple et documentée) :
        - connect=False          → "Alerte"  : perte de liaison = plus critique
                                                (plus aucune production remontée)
        - warn=True / codes non vide → "Warning" : le micro répond mais signale
                                                une anomalie (sur-tension, sur-temp…)
        - sinon                  → "Normal"

        Le message d'erreur est dérivé du 1er code d'alarme (protobuf day_data,
        enum AlarmReason) ; si seul le booléen cloud est disponible, message
        générique. Retourne (statut, message)."""
        if not connect:
            return "Alerte", "Micro-onduleur hors ligne"
        if warn or codes:
            code = codes[0] if codes else None
            if code is not None:
                msg = ALARM_MESSAGES.get(code, f"Alarme (code {code})")
            else:
                msg = "Anomalie détectée"
            return "Warning", msg
        # Sentinelle "OK" (et non "" vide) : le core Jeedom refuse les valeurs vides
        # (core/api/jeeApi.php l.114 : `init('value') != ''` → event jamais déclenché).
        return "Normal", "OK"

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
            # ---------- Santé des micros : warn_data (cloud) + codes (protobuf) ----------
            try:
                # warn_data {warn, connect} : état agrégé exposé par le cloud
                now = time.time()
                for sn, al in self.api.get_micro_alarms(self.sid).items():
                    status, msg = self._alarm_status(
                        warn=al["warn"], connect=al["connect"],
                        codes=self.alarm_codes.get(sn, []))
                    eq = f"micro-{sn}"
                    self.push(eq, "warn", 1 if al["warn"] else 0)
                    self.push(eq, "status", status)
                    self.push(eq, "alarm_msg", msg)
                    # Zeroing hors ligne (v0.1.8) : suit le flag cloud `connect`
                    # (même source que le statut "Alerte") pour horodater la coupure.
                    if al["connect"]:
                        if sn in self.offline_since:
                            log(f"Micro {sn} de retour — valeurs réelles rétablies "
                                f"(W immédiat, V/A au prochain cycle ≤ 5 min)")
                        self.offline_since.pop(sn, None)
                        self.zero_logged.discard(sn)
                    else:
                        self.offline_since.setdefault(sn, now)
                        stale = (now - self.offline_since[sn]) >= OFF_LINE_DELAY
                        if sn not in self.zero_logged and stale:
                            self.zero_logged.add(sn)
                            log(f"Micro {sn} hors ligne > {OFF_LINE_DELAY // 60} min — "
                                f"V/A/production forcées à 0 (comportement nuit)")
            except Exception as e:
                log(f"Santé micros échoué : {e}")
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
                # codes d'alarme du jour (champs int16) — consommés par slow_poll
                # pour le statut "Warning"/"Alerte" et le message d'erreur.
                self.alarm_codes[sn] = entry.get("alarm_codes") or []
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
