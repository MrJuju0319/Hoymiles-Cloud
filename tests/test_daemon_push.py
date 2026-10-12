"""Tests du filtre de push du démon (mise en file, zeroing hors ligne).

Ne fait aucun appel réseau : seule la file d'attente interne est inspectée.
"""
import time

from hoymiles_daemon import HoymilesDaemon


def make_daemon():
    # __init__ ne lit pas le fichier de configuration : rien n'est chargé ici
    d = HoymilesDaemon("/nonexistent/config.json")
    d.mapping = {"micro-A": {"eq_id": 1, "cmds": {"pac": 11, "uac": 12}}}
    d.micros = ["A"]
    d.config = {"apikey": "test", "jeedom_url": "http://127.0.0.1", "delta_threshold": 1}
    return d


def test_valeur_absente_non_mise_en_file():
    """None ne doit jamais partir : urlencode() l'écrirait comme « None ». """
    d = make_daemon()
    d.push("micro-A", "pac", None)
    assert d.q.empty()


def test_micro_hors_ligne_force_zero():
    d = make_daemon()
    d.offline_since = {"A": time.time() - 400}
    d.push("micro-A", "pac", 300.0)
    eq, cmd, value, _threshold, _force = d.q.get_nowait()
    assert (eq, cmd, value) == ("micro-A", "pac", 0)


def test_micro_hors_ligne_valeur_absente_deviant_zero():
    """Un micro hors ligne avec donnée manquante doit tout de même remettre la
    valeur à 0 dans Jeedom (sinon l'ancienne valeur reste affichée)."""
    d = make_daemon()
    d.offline_since = {"A": time.time() - 400}
    d.push("micro-A", "uac", None)
    assert d.q.get_nowait()[2] == 0


def test_valeur_normale_transmise_telle_quelle():
    d = make_daemon()
    d.push("micro-A", "pac", 300.5, 1)
    assert d.q.get_nowait()[2] == 300.5


def test_temperature_non_zeroee_hors_ligne():
    d = make_daemon()
    d.mapping["micro-A"]["cmds"]["temp"] = 13
    d.offline_since = {"A": time.time() - 400}
    d.push("micro-A", "temp", 41.5)
    assert d.q.get_nowait()[2] == 41.5


def test_seuil_transmis_au_pusher():
    d = make_daemon()
    d.push("micro-A", "pac", 300.0, 5, True)
    eq, cmd, value, threshold, force = d.q.get_nowait()
    assert (eq, cmd, value, threshold, force) == ("micro-A", "pac", 300.0, 5, True)


# ---------- Multi-installations (compte à plusieurs stations) ----------
def test_station_micros_cible_la_bonne_station():
    d = make_daemon()
    d.stations = [{"sid": 1, "micros": ["A"]}, {"sid": 22, "micros": ["B", "C"]}]
    assert d.station_micros("station-1") == ["A"]
    assert d.station_micros("station-22") == ["B", "C"]
    assert d.station_micros("station-3") == []


def test_zeroing_station_ne_depend_que_de_ses_micros():
    d = make_daemon()
    d.mapping = {"station-1": {"cmds": {"real_power": 1}},
                 "station-2": {"cmds": {"real_power": 2}}}
    d.stations = [{"sid": 1, "micros": ["A"]}, {"sid": 2, "micros": ["B"]}]
    d.offline_since = {"A": time.time() - 400}
    d.push("station-1", "real_power", 500.0)
    assert d.q.get_nowait()[2] == 0          # station 1 : son micro est hors ligne
    d.push("station-2", "real_power", 500.0)
    assert d.q.get_nowait()[2] == 500.0      # station 2 : son micro produit


def test_chemins_runtime_issus_de_la_config():
    """Le dossier temporaire est fourni par Jeedom (config['tmp_dir']) : aucun
    chemin /tmp/jeedom/... en dur (certains hôtes le déplacent)."""
    d = make_daemon()
    d.tmp_dir = "/var/lib/jeedom-tmp/hoymilescloud"
    assert d.pid_file == "/var/lib/jeedom-tmp/hoymilescloud/daemon.pid"
    assert d.status_file == "/var/lib/jeedom-tmp/hoymilescloud/status.json"


def test_langue_lue_depuis_la_config():
    from hoymiles_logic import norm_lang
    assert norm_lang("en_US") == "en"      # installation anglophone
    assert norm_lang("fr_FR") == "fr"
    d = make_daemon()
    d.language = "en"
    status, msg = d._alarm_status(warn=False, connect=False, codes=[])
    assert status == "Alert" and "offline" in msg
