"""Tests de la logique pure du démon (hoymiles_logic).

Ces règles ont déjà provoqué une régression silencieuse en production (valeurs
figées d'un micro hors ligne affichées comme réelles, faux « hors ligne » la
nuit) : elles sont désormais couvertes, sans réseau ni Jeedom.

Aucune donnée réelle : identifiants d'équipement fictifs.
"""
import pytest

from hoymiles_logic import (ALARM_MESSAGES_EN, ELECTRICAL_CMDS, OFF_LINE_DELAY,
                            STATUS_CODES, alarm_status, burst_delay_ms, entry_ports,
                            norm_lang, offline_zero, status_code)

NOW = 1_800_000_000.0
MICROS = ["SN0000000001", "SN0000000002"]


def offline(delay, sn=None):
    """Etat offline_since : tous les micros (ou un seul) hors ligne depuis delay."""
    targets = MICROS if sn is None else [sn]
    return {s: NOW - delay for s in targets}


# ---------- Zeroing hors ligne ----------
def test_micro_hors_ligne_au_dela_du_delai_zero_les_valeurs_electriques():
    state = offline(OFF_LINE_DELAY + 100)
    for cmd in ("pac", "p1", "p2", "up1", "up2", "ip1", "ip2", "uac", "freq"):
        assert offline_zero(f"micro-{MICROS[0]}", cmd, state, MICROS, NOW) is True


def test_micro_hors_ligne_recent_ne_zero_pas():
    state = offline(60)
    assert offline_zero(f"micro-{MICROS[0]}", "pac", state, MICROS, NOW) is False


def test_micro_en_ligne_ne_zero_pas():
    assert offline_zero(f"micro-{MICROS[0]}", "pac", {}, MICROS, NOW) is False


def test_temperature_jamais_zeroee():
    """`temp` est exclue : valeur thermique, elle ne tombe pas à 0 la nuit."""
    state = offline(OFF_LINE_DELAY + 600)
    assert offline_zero(f"micro-{MICROS[0]}", "temp", state, MICROS, NOW) is False


def test_compteurs_energie_jamais_zeroes():
    state = offline(OFF_LINE_DELAY + 600)
    assert offline_zero(f"micro-{MICROS[0]}", "e1", state, MICROS, NOW) is False


def test_station_real_power_zeroe_si_tous_les_micros_sont_hors_ligne():
    state = offline(OFF_LINE_DELAY + 10)
    assert offline_zero("station-1", "real_power", state, MICROS, NOW) is True


def test_station_real_power_conservee_si_un_micro_produit():
    """On ne masque jamais la production des micros sains."""
    state = offline(OFF_LINE_DELAY + 10, sn=MICROS[0])
    assert offline_zero("station-1", "real_power", state, MICROS, NOW) is False


def test_multi_sites_les_micros_d_une_autre_station_n_influent_pas():
    """Sur un compte à plusieurs installations, le zeroing d'une station ne doit
    dépendre que de SES micros (l'appelant passe la liste de la station)."""
    state = {MICROS[0]: NOW - OFF_LINE_DELAY - 10}
    # Station 2 (micro en ligne) → jamais zéroée
    assert offline_zero("station-2", "real_power", state, ["SN0000000002"], NOW) is False
    # Station 1 (micro unique hors ligne) → zéroée
    assert offline_zero("station-1", "real_power", state, [MICROS[0]], NOW) is True


def test_station_energies_jamais_zeroees():
    state = offline(OFF_LINE_DELAY + 600)
    for cmd in ("today_eq", "month_eq", "year_eq", "total_eq", "self_rate", "co2"):
        assert offline_zero("station-1", cmd, state, MICROS, NOW) is False


def test_commande_inconnue_ne_zero_pas():
    state = offline(OFF_LINE_DELAY + 600)
    assert offline_zero(f"micro-{MICROS[0]}", "status", state, MICROS, NOW) is False


def test_ports_3_et_4_sont_dans_les_commandes_electriques():
    """Régression : les micros 4 MPPT doivent aussi être zéroés."""
    for cmd in ("p3", "p4", "up3", "up4", "ip3", "ip4"):
        assert cmd in ELECTRICAL_CMDS


# ---------- Statuts de santé ----------
def test_statut_alerte_si_deconnecte():
    assert alarm_status(False, False, [])[0] == "Alerte"


def test_statut_warning_avec_code_alarme():
    status, msg = alarm_status(True, True, [6])
    assert status == "Warning"
    assert "température" in msg.lower()


def test_statut_warning_sans_code_detaille():
    status, msg = alarm_status(True, True, [])
    assert status == "Warning"
    assert msg == "Anomalie détectée"


def test_statut_normal_avec_sentinelle_ok():
    """Sentinelle « OK » et non chaîne vide : le core Jeedom n'émet pas
    d'événement pour une valeur vide."""
    status, msg = alarm_status(False, True, [])
    assert (status, msg) == ("Normal", "OK")


def test_code_alarme_inconnu_reste_lisible():
    status, msg = alarm_status(True, True, [999])
    assert status == "Warning" and "999" in msg


# ---------- Statuts localisés (installation non francophone) ----------
def test_statuts_en_anglais():
    assert alarm_status(False, False, [], lang="en_US")[0] == "Alert"
    assert alarm_status(False, True, [], lang="en_US") == ("Normal", "OK")
    status, msg = alarm_status(True, True, [6], lang="en")
    assert status == "Warning" and "temperature" in msg.lower()


def test_langue_normalisee():
    assert norm_lang("en_US") == "en"
    assert norm_lang("EN") == "en"
    assert norm_lang("fr_FR") == "fr"
    assert norm_lang(None) == "fr"
    assert norm_lang("de_DE") == "fr"  # langue non gérée → repli français


def test_tables_alarmes_completes():
    """Une entrée pour chacun des 16 codes du protocole, dans les deux langues."""
    assert sorted(ALARM_MESSAGES_EN.keys()) == list(range(1, 17))


def test_codes_de_statut_stables():
    """Le code numérique est l'interface stable pour les scénarios : il ne doit
    pas dépendre de la langue."""
    assert status_code("Alerte") == STATUS_CODES["alert"]
    assert status_code("Alert") == STATUS_CODES["alert"]
    assert status_code("Warning") == STATUS_CODES["warning"]
    assert status_code("Normal") == STATUS_CODES["normal"]
    assert status_code("") == STATUS_CODES["normal"]
    assert status_code(None) == STATUS_CODES["normal"]


# ---------- Ports dynamiques ----------
def test_entry_ports_trie_et_convertit():
    assert entry_ports({"ports": {2: {}, 1: {}, "3": {}}}) == [1, 2, 3]


def test_entry_ports_vide():
    assert entry_ports({}) == []
    assert entry_ports(None) == []


def test_entry_ports_micro_4_mppt():
    assert entry_ports({"ports": {1: {}, 2: {}, 3: {}, 4: {}}}) == [1, 2, 3, 4]


# ---------- Cadence burst ----------
def test_burst_respecte_le_serveur_quand_il_est_plus_lent():
    assert burst_delay_ms(3000, 2) == 3000


def test_burst_intervalle_utilisateur_sert_de_plancher():
    """`burst_interval` était stocké mais jamais lu : il doit brider les rafales."""
    assert burst_delay_ms(1500, 5) == 5000


def test_burst_plancher_par_defaut():
    assert burst_delay_ms(1500, 2) == 2000
    assert burst_delay_ms(None, 0) == 1500  # valeur invalide → minimum technique 1 s
