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
