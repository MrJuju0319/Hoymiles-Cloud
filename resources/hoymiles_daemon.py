#!/usr/bin/env python3
"""Hoymiles Cloud daemon — pousse les données S-Miles vers Jeedom.

Architecture (threads + file d'attente, v0.1.5 conservée) :

- 3 threads COLLECTEURS indépendants (un blocage réseau ne fige jamais les autres) :
    * burst   : m:0 + m:3 au rythme du serveur (dly ~1,5-3 s) — puissances temps réel
    * slow    : count_station_real_data toutes les 60 s — énergies, statut, heartbeat
    * day     : down_module_day_data toutes les 5 min — tensions/courants/températures
- 1 thread PUSHER : consomme une file d'attente (queue.Queue) et fait les requêtes
  HTTP vers Jeedom de façon séquentielle (timeout strict 10 s).
- MULTI-INSTALLATIONS : le démon parcourt TOUTES les stations du compte
  (plusieurs maisons, compte installateur…). Le temps réel (burst) est plafonné
  par le réglage « Stations en temps réel » pour ne pas marteler l'API ; les
  stations au-delà restent couvertes par le polling énergies (60 s) et les
  données électriques (5 min). Chaque station a ses propres commandes, son
  heartbeat et son zeroing hors ligne (les micros d'une installation n'influent
  jamais sur une autre).
- Timeouts stricts partout (API ≤ 10 s, day_data 15 s, push 10 s) : un blocage
  réseau = un appel échoué, jamais un démon figé.
- Log : écrit par le démon lui-même (WatchedFileHandler) dans le log Jeedom — il
  se réattache après chaque rotation/chunk, sinon le fichier devenait creux et
  rempli d'octets NUL. Niveau réglable (Normal / Détaillé / Réduit).
- Aucune écriture disque en fonctionnement normal (important carte SD Raspberry Pi) :
  le pid file est écrit 1× au démarrage, la config est relue depuis le dossier
  temporaire du plugin (fourni par Jeedom dans la config), et status.json n'est
  écrit QUE lors d'un CHANGEMENT d'état (rare).
- Heartbeat : commande `daemon` (station) poussée en FORCE toutes les 60 s → un
  scénario Jeedom peut alerter si la commande n'est plus mise à jour depuis X min.
- Auto-refresh token : tout appel répondant status=100 (token expiré) déclenche un
  re-login + retry, sans redémarrage (verrouillé par lock : pas de double login).
- Zeroing hors ligne : micro hors ligne (flag cloud `connect`) depuis plus de
  OFF_LINE_DELAY (300 s) → valeurs électriques (V/A/W/Hz) forcées à 0
  (comportement « pleine nuit »). La température interne reste à sa dernière
  valeur connue.
- Ports dynamiques : les séries day_data sont poussées pour TOUS les ports
  présents (2 MPPT sur un HMS-1000-2WB, 4 sur un 4 MPPT).
- Statuts localisés (fr/en selon la langue de Jeedom) + commande `status_code`
  numérique (0 normal, 1 avertissement, 2 alerte) pour des scénarios
  indépendants de la langue.
- Logique pure (zeroing, statuts, cadence, ports) dans hoymiles_logic.py,
  couverte par tests/ (pytest + CI GitHub Actions).

Usage: hoymiles_daemon.py --config /tmp/jeedom/hoymilescloud/config.json
"""
import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
import urllib.parse
from logging.handlers import WatchedFileHandler

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hoymiles_api import (HoymilesCloudApi, URI_REFRESH_MS, parse_day_data,
                          jeedom_decrypt)
from hoymiles_logic import (ELECTRICAL_CMDS, OFF_LINE_DELAY, alarm_status,
                            burst_delay_ms, entry_ports, norm_lang, offline_zero,
                            status_code)

# Dossier temporaire de repli si la config n'en fournit pas (Jeedom le passe
# dans config['tmp_dir'] : certains hôtes configurent un autre chemin).
DEFAULT_TMP_DIR = "/tmp/jeedom/hoymilescloud"
PUSH_TIMEOUT = 10      # timeout strict des push Jeedom
HEARTBEAT_CMD = "daemon"  # commande binaire de santé, poussée en force

LOGGER = logging.getLogger("hoymilescloud")


def setup_logging(path=None, level="info"):
    """Le démon écrit lui-même son log (fichier fourni par Jeedom).

    WatchedFileHandler : le handler détecte que le fichier a été renommé ou
    tronqué (rotation / « chunk » par Jeedom) et le rouvre automatiquement.
    Sans cela, le démon continue d'écrire dans l'inode déplacé → fichier creux
    rempli d'octets NUL et lignes perdues (constaté en production : log de
    7,9 Mo illisible pour grep).
    """
    lvl = getattr(logging, str(level or "info").upper(), logging.INFO)
    LOGGER.setLevel(lvl)
    for h in list(LOGGER.handlers):
        LOGGER.removeHandler(h)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = WatchedFileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        LOGGER.addHandler(handler)
    except Exception as e:  # dépend du système de fichiers
        print(f"Log fichier indisponible ({e}) — sortie console uniquement", flush=True)


def log(msg, level=logging.INFO):
    """Log applicatif. Repli sur la sortie standard si aucun fichier n'est
    disponible (le log console est capturé par le lanceur Jeedom)."""
    if LOGGER.handlers:
        LOGGER.log(level, msg)
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


class HoymilesDaemon:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = {}
        self.mapping = {}
        self.config_mtime = 0
        self.config_last_check = 0
        self.tmp_dir = DEFAULT_TMP_DIR
        self.language = "fr"
        self.api = None
        self.last_pushed = {}   # (eq, cmd) -> valeur — cache EN MÉMOIRE (aucun FS)
        self.burst_failures = 0
        self.burst_ok = False
        self._last_no_uri_log = 0  # log espacé "pas d'URI burst" (1×/10 min)
        self.slow_failures = 0
        self.micro_missing = {}  # sn -> cycles consécutifs sans réponse
        self.alarm_codes = {}    # sn -> [codes d'alarme] (du protobuf day_data)
        self.offline_since = {}  # sn -> ts du passage hors ligne (flag cloud connect)
        self.zero_logged = set()  # sn dont le zeroing a déjà été loggué
        self.stations = []       # [{sid, name, micros, uri, uri_at, micro_missing}]
        self.micros = []         # toutes les sn du compte (toutes stations)
        self.micro_id_to_sn = {}  # id -> sn
        self.micro_ports = {}    # sn -> [ports MPPT réellement exposés]

        # file d'attente + threads
        self.q = queue.Queue(maxsize=2000)
        self.stop_event = threading.Event()
        self.push_lock = threading.Lock()
        self.threads = []

        # état publié (status.json) — écrit uniquement sur changement
        self.status = {
            "state": "starting", "ts": time.time(), "error": None,
            "burst_ok": False, "slow_ok": False, "day_ok": False,
            "last_data": None, "degraded_since": None, "stations": 0, "micros": 0,
        }
        self._status_sig = None

    # ---------- Chemins runtime (fournis par Jeedom) ----------
    @property
    def pid_file(self):
        return os.path.join(self.tmp_dir, "daemon.pid")

    @property
    def status_file(self):
        return os.path.join(self.tmp_dir, "status.json")

    # ---------- Config / mapping ----------
    def load_config(self):
        """Relecture de la config écrite par Jeedom — au plus toutes les 5 s
        (un stat() par cycle est sans impact, mais restons frugal)."""
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
        # Dossier temporaire et langue : fournis par Jeedom (aucun chemin en dur)
        self.tmp_dir = self.config.get("tmp_dir") or DEFAULT_TMP_DIR
        self.language = norm_lang(self.config.get("language", "fr_FR"))
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
               self.status["day_ok"], self.status["last_data"], self.status["error"],
               self.status["stations"], self.status["micros"])
        if sig == self._status_sig:
            return  # rien n'a changé → zéro écriture disque
        self._status_sig = sig
        try:
            os.makedirs(self.tmp_dir, exist_ok=True)
            tmp = self.status_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.status, f)
            os.replace(tmp, self.status_file)  # atomique
        except Exception as e:
            log(f"status.json : {e}")

    # ---------- Push Jeedom (file d'attente, non bloquant) ----------
    def station_micros(self, eq_logical):
        """Micros de la station « station-<sid> » (zeroing ciblé)."""
        sid = eq_logical[len("station-"):]
        for st in self.stations:
            if str(st["sid"]) == str(sid):
                return st["micros"]
        return []

    def _offline_zero(self, eq_logical, cmd_logical):
        """Délègue à hoymiles_logic.offline_zero (fonction pure testée)."""
        if eq_logical.startswith("station-"):
            return offline_zero(eq_logical, cmd_logical, self.offline_since,
                                self.station_micros(eq_logical), time.time(),
                                OFF_LINE_DELAY)
        return offline_zero(eq_logical, cmd_logical, self.offline_since,
                            self.micros, time.time(), OFF_LINE_DELAY)

    def push(self, eq_logical, cmd_logical, value, threshold=None, force=False):
        """Mise en file — le thread pusher s'occupe du HTTP (timeout strict).
        force=True (heartbeat) : contourne le push intelligent.
        Micro hors ligne > OFF_LINE_DELAY : les valeurs électriques sont
        remplacées par 0 avant mise en file (aucune valeur figée remontée).
        Une valeur absente (None) est ignorée — sinon urlencode() la
        transmettrait à Jeedom sous la forme de la chaîne « None »."""
        if self._offline_zero(eq_logical, cmd_logical):
            value = 0
        if value is None:
            return
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
            url = self.config["jeedom_url"].rstrip("/") + "/core/api/jeeApi.php?" + urllib.parse.urlencode(params)
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
    def _burst_station(self, st):
        """Burst d'UNE station : URI dédiée + m:0 (station) + m:3 (micros).

        Retourne (délai_ms, uri_disponible). Une station en veille (pas d'URI :
        nuit, ou flux temps réel non exposé) ne bloque pas les autres."""
        sid = st["sid"]
        try:
            if not st["uri"] or (time.time() - st["uri_at"]) > URI_REFRESH_MS / 1000:
                st["uri"] = self.api.get_burst_uri(sid)
                st["uri_at"] = time.time()
                if st["uri"]:
                    log(f"URI burst rafraîchie (station {sid})", logging.DEBUG)
            if not st["uri"]:
                return 300000, False

            t = self.config.get("delta_threshold", 1)
            dly = 1500
            # m:0 — station
            code, resp = self.api.burst(st["uri"], mode=0)
            if resp.get("status") != "0":
                raise RuntimeError(f"burst m:0 station {sid} → {resp.get('status')} {resp.get('message')}")
            data = resp.get("data") or {}
            dly = data.get("dly", dly)
            power = data.get("power") or {}
            eq_st = f"station-{sid}"
            if power.get("pv") is not None:
                self.push(eq_st, "real_power", power["pv"], t)
            # ⚠️ `power["pvr"]` n'est PAS poussé dans la commande
            # Autoconsommation (%) : cet indicateur du burst n'a pas l'unité de
            # la commande, alimentée par le cloud (count_station_real_data).

            # m:3 — micros de CETTE station
            micros = st["micros"]
            if micros:
                code, resp = self.api.burst(st["uri"], mode=3, mis=micros)
                if resp.get("status") != "0":
                    raise RuntimeError(f"burst m:3 station {sid} → {resp.get('status')} {resp.get('message')}")
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
                    # Uniquement les ports réellement exposés par le micro
                    # (port_array du cloud) : plus de push fantôme vers p3/p4
                    # sur un micro 2 MPPT.
                    for p in self.micro_ports.get(sn, [1, 2]):
                        self.push(eq, f"p{p}", mi.get(f"p{p}"), t)
                    self.push(eq, "connect", 1)
                for sn in micros:
                    if sn not in seen:
                        self.micro_missing[sn] = self.micro_missing.get(sn, 0) + 1
                        if self.micro_missing[sn] >= 5:
                            self.push(f"micro-{sn}", "connect", 0)
            self.burst_failures = 0
            self.burst_ok = True
            self._set_status(burst_ok=True, error=None)
            return dly, True
        except Exception as e:
            self.burst_failures += 1
            log(f"Burst échec #{self.burst_failures} (station {sid}) : {e}")
            if self.burst_failures >= 3:
                log("3 échecs burst — mode dégradé (polling seul)")
                self.burst_ok = False
                self._set_status(burst_ok=False, error=str(e)[:120])
            return 30000, True

    def burst_poll(self):
        """Burst de toutes les stations suivies en temps réel (plafonné par
        « Stations en temps réel » : protection de l'API et de la bande
        passante pour les comptes multi-sites / installateurs)."""
        tracked = self.stations[:max(1, int(self.config.get("burst_max_stations", 3)))]
        if not tracked:
            return 30000
        dlys = []
        with_uri = 0
        for st in tracked:
            dly, has_uri = self._burst_station(st)
            dlys.append(dly)
            if has_uri:
                with_uri += 1
        if with_uri == 0:
            # Aucune station ne produit (nuit) : ce n'est PAS une panne, le
            # polling lent continue. Log espacé, nouvel essai dans 5 min.
            if time.time() - self._last_no_uri_log > 600:
                self._last_no_uri_log = time.time()
                log("Aucune URI burst (stations en veille la nuit ?) — "
                    "polling lent seul, nouvel essai dans 5 min")
            return 300000
        # Rythme : `dly` imposé par le serveur, avec l'intervalle minimum
        # configuré comme plancher (paramètre « Intervalle minimum burst »).
        return burst_delay_ms(max(dlys), self.config.get("burst_interval", 2))

    def _burst_loop(self):
        while not self.stop_event.is_set():
            try:
                dly = 10000
                if self.stations:
                    dly = self.burst_poll()
                self.stop_event.wait(max(dly, 2000) / 1000)
            except Exception as e:
                log(f"Burst loop : {e}")
                self.stop_event.wait(5)

    # ---------- Santé micros ----------
    def _alarm_status(self, warn, connect, codes):
        """Statut + message localisés (délègue à hoymiles_logic.alarm_status)."""
        return alarm_status(warn, connect, codes, lang=self.language)

    # ---------- Boucle lente (énergies + statut + heartbeat) ----------
    def _slow_station(self, st):
        """Énergies + statut + heartbeat pour UNE station.
        Retourne l'horodatage cloud de la dernière donnée (str) si OK, None sinon."""
        sid = st["sid"]
        st_eq = f"station-{sid}"
        try:
            d = self.api.get_realtime(sid)
            if not d:
                log(f"Slow poll : réponse vide de count_station_real_data (station {sid}, rate-limit silencieux ?) — nouvel essai au prochain cycle")
                return None
            log(f"Slow poll OK (station {sid}) : today_eq={d.get('today_eq')} last={d.get('last_data_time')}",
                logging.DEBUG)
            t = self.config.get("delta_threshold", 1)
            self.push(st_eq, "real_power", d.get("real_power"), t)
            self.push(st_eq, "today_eq", d.get("today_eq"), t)
            self.push(st_eq, "month_eq", d.get("month_eq"), t)
            self.push(st_eq, "total_eq", d.get("total_eq"), t)
            self.push(st_eq, "year_eq", d.get("year_eq"), t)
            # Équivalents en kWh (simple conversion) — seuil serré 0,01 : avec le
            # seuil standard de 1, aucune variation de kWh ne serait poussée.
            for cmd, src in (("today_kwh", "today_eq"), ("month_kwh", "month_eq"),
                             ("year_kwh", "year_eq"), ("total_kwh", "total_eq")):
                if d.get(src) is not None:
                    self.push(st_eq, cmd, round(float(d[src]) / 1000.0, 3), 0.01)
            self.push(st_eq, "self_rate", d.get("self_rate"), t)
            self.push(st_eq, "co2", d.get("co2_emission_reduction"), t)
            self.push(st_eq, "last_data_time", d.get("last_data_time", ""))
            self.push(st_eq, "online", 1 if d.get("is_null") == 0 else 0)
            # heartbeat santé du démon — FORCÉ (contourne le push intelligent) :
            # la commande `daemon` est mise à jour toutes les 60 s par station ;
            # un scénario peut alerter si elle n'est plus rafraîchie.
            self.push(st_eq, HEARTBEAT_CMD, 1, force=True)

            # ---------- Santé des micros de la station ----------
            try:
                now = time.time()
                for sn, al in self.api.get_micro_alarms(sid).items():
                    status, msg = self._alarm_status(
                        warn=al["warn"], connect=al["connect"],
                        codes=self.alarm_codes.get(sn, []))
                    eq = f"micro-{sn}"
                    self.push(eq, "warn", 1 if al["warn"] else 0)
                    self.push(eq, "status", status)
                    self.push(eq, "status_code", status_code(status))
                    self.push(eq, "alarm_msg", msg)
                    # Zeroing hors ligne : suit le flag cloud `connect`
                    # (même source que le statut d'alerte) pour horodater la coupure.
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
                log(f"Santé micros échoué (station {sid}) : {e}")
            return d.get("last_data_time")
        except Exception as e:
            log(f"Slow poll échoué (station {sid}) : {e}")
            return None

    def slow_poll(self):
        """Énergies + statut + heartbeat de toutes les stations."""
        if not self.stations:
            return
        ok = 0
        last_data = None
        for st in self.stations:
            ld = self._slow_station(st)
            if ld:
                ok += 1
                if ld > (last_data or ""):
                    last_data = ld
        if ok == 0:
            self.slow_failures += 1
            if self.slow_failures >= 3:
                self._set_status(slow_ok=False, error="slow poll vide x3 (rate-limit ?)")
            return
        self.slow_failures = 0
        self._set_status(slow_ok=True, error=None,
                         last_data=last_data or self.status.get("last_data"))

    def _slow_loop(self):
        interval = 60
        while not self.stop_event.is_set():
            try:
                self.load_config()
                interval = max(15, int(self.config.get("slow_interval", 60)))
                if self.stations:
                    self.slow_poll()
            except Exception as e:
                log(f"Slow loop : {e}")
            self.stop_event.wait(interval)

    # ---------- Boucle données jour (tensions/courants/températures) ----------
    def _day_data_station(self, st):
        """down_module_day_data (protobuf) pour UNE station : tension réseau,
        fréquence, température interne du micro et tension/courant DC par port
        (dernier bucket 5 min, grain identique à l'app S-Miles)."""
        sid = st["sid"]
        blob = self.api.get_day_data(sid, time.strftime("%Y-%m-%d"))
        if not blob:
            log(f"Day data : réponse vide/refusée (station {sid}) — nouvel essai au prochain cycle")
            return False
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
            for port in entry_ports(entry):
                # Ports réellement exposés par le micro (2 MPPT sur un
                # HMS-1000-2WB, 4 sur un 4 MPPT) : l'ancien code filtrait
                # `if port not in (1, 2)` et tronquait les micros 4 MPPT.
                p = entry["ports"][port]
                if p.get("up") is not None:
                    self.push(eq, f"up{port}", round(p["up"], 1), t)
                if p.get("ip") is not None:
                    self.push(eq, f"ip{port}", round(p["ip"], 2), t)
                # énergie cumulée du jour par port (Wh) — jamais zéroée hors
                # ligne (hors ELECTRICAL_CMDS) : c'est un compteur, pas une
                # mesure instantanée.
                if p.get("e") is not None:
                    self.push(eq, f"e{port}", round(p["e"], 1), t)
            # codes d'alarme du jour (champs int16) — consommés par le slow poll
            # pour le statut et le message d'erreur.
            self.alarm_codes[sn] = entry.get("alarm_codes") or []
        log(f"Day data OK (station {sid}) : {len(data.get('micros', {}))} micro(s) — uac/temp/up/ip mis à jour",
            logging.DEBUG)
        return True

    def day_data_poll(self):
        ok = 0
        for st in self.stations:
            try:
                if self._day_data_station(st):
                    ok += 1
            except Exception as e:
                log(f"Day data échoué (station {st['sid']}) : {e}")
        if not self.stations:
            return
        if ok == 0:
            self._set_status(day_ok=False, error="day data indisponible")
        else:
            self._set_status(day_ok=True, error=None)

    def _day_loop(self):
        interval = 300
        while not self.stop_event.is_set():
            try:
                self.load_config()
                interval = max(300, int(self.config.get("day_data_interval", 300)))
                if self.stations:
                    self.day_data_poll()
            except Exception as e:
                log(f"Day loop : {e}")
            self.stop_event.wait(interval)

    # ---------- Démarrage ----------
    def discover(self):
        """Recense TOUTES les stations du compte et leurs micros (multi-sites).

        Rien n'est codé en dur : identifiants, noms, nombre de stations, de
        micros et de ports viennent du cloud."""
        stations = self.api.get_stations()
        self.stations = []
        self.micro_id_to_sn = {}
        self.micro_ports = {}
        for s in stations:
            sid = s.get("id")
            if not sid:
                continue
            entry = {"sid": sid, "name": s.get("name", ""), "micros": [],
                     "uri": None, "uri_at": 0}
            for m in self.api.get_micros(sid):
                sn = m.get("sn")
                if not sn:
                    continue
                entry["micros"].append(sn)
                if m.get("id"):
                    self.micro_id_to_sn[m["id"]] = sn
                ports = []
                for p in (m.get("port_array") or []):
                    try:
                        ports.append(int(p))
                    except (TypeError, ValueError):
                        continue
                self.micro_ports[sn] = sorted(ports) or [1, 2]
            self.stations.append(entry)
        self.micros = [sn for st in self.stations for sn in st["micros"]]
        self.status["stations"] = len(self.stations)
        self.status["micros"] = len(self.micros)
        if self.stations:
            resume = ", ".join(f"{st['sid']} ({len(st['micros'])} micro(s))" for st in self.stations)
            log(f"{len(self.stations)} station(s) — {len(self.micros)} micro(s) : {resume}")
        else:
            log("Aucune station sur ce compte — attente de configuration")

    def run(self):
        # Log configuré au plus tôt (chemin fourni par Jeedom, ou HOYMILES_LOG
        # pour un lancement manuel) : les erreurs de démarrage doivent être
        # visibles dans le log du plugin, pas seulement sur la sortie standard.
        setup_logging(os.environ.get("HOYMILES_LOG"),
                      os.environ.get("HOYMILES_LOG_LEVEL", "info"))
        log("Démarrage du démon Hoymiles Cloud")
        self.load_config()
        setup_logging(self.config.get("log"), self.config.get("log_level", "info"))
        self.api = HoymilesCloudApi(self.config["user"], self.config["password"],
                                    profile=self.config.get("profile", "auto"))
        self.api.ensure_token()
        log(f"Login OK ({self.api.method}) — langue {self.language}")

        self.discover()

        # pid file (1 seule écriture au démarrage)
        os.makedirs(self.tmp_dir, exist_ok=True)
        with open(self.pid_file, "w") as f:
            f.write(str(os.getpid()))

        self._set_status(state="ok", stations=len(self.stations), micros=len(self.micros))

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
