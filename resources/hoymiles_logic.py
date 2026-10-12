#!/usr/bin/env python3
"""Logique pure du démon Hoymiles Cloud — testable sans réseau ni Jeedom.

Ces fonctions ont été extraites de hoymiles_daemon.py pour être couvertes par
la suite de tests (tests/test_logic.py) : ce sont elles qui décident du
comportement « nuit » et des statuts de santé, deux domaines où une régression
silencieuse a déjà eu lieu (v0.1.8).
"""
from hoymiles_api import ALARM_MESSAGES

# Commandes électriques concernées par le forçage à 0 quand un micro est hors
# ligne (tensions en V, courants en A, puissances en W, fréquence en Hz).
# `temp` est volontairement EXCLUE : en pleine nuit la température interne du
# micro ne tomberait pas à 0 — une valeur figée y est moins trompeuse qu'un 0.
ELECTRICAL_CMDS = {
    "uac", "freq",
    "up1", "up2", "up3", "up4",
    "ip1", "ip2", "ip3", "ip4",
    "pac", "p1", "p2", "p3", "p4",
}

# Délai (s) après lequel un micro hors ligne voit ses valeurs électriques forcées à 0
OFF_LINE_DELAY = 300


def offline_zero(eq_logical, cmd_logical, offline_since, micros, now, delay=OFF_LINE_DELAY):
    """La valeur doit-elle être forcée à 0 ?

    Sources : `offline_since` est alimenté UNIQUEMENT par le flag cloud
    `connect` (warn_data de select_by_station, show_warn=1) — même source que le
    statut « Alerte ». Une coupure réseau locale ou un rate-limit API ne
    déclenche donc JAMAIS de faux zéro.

    Station : seule `real_power` peut être forcée à 0, et uniquement si TOUS les
    micros sont hors ligne depuis `delay` (sinon on masquerait la production des
    micros sains). Les compteurs d'énergie, %, CO2… ne sont jamais touchés.
    """
    if eq_logical.startswith("station-"):
        if cmd_logical == "real_power" and micros:
            return all(s in offline_since and (now - offline_since[s]) >= delay
                       for s in micros)
        return False
    if cmd_logical not in ELECTRICAL_CMDS:
        return False
    if eq_logical.startswith("micro-"):
        sn = eq_logical[len("micro-"):]
        since = offline_since.get(sn)
        return since is not None and (now - since) >= delay
    return False


def alarm_status(warn, connect, codes, messages=None):
    """Traduit l'état brut S-Miles en statut lisible pour Jeedom.

    - connect=False              → « Alerte » (perte de liaison : plus aucune
                                    production remontée, c'est le plus grave)
    - warn=True / codes non vide → « Warning » (le micro répond mais signale une
                                    anomalie : sur-tension, sur-température…)
    - sinon                      → « Normal »

    Le message est dérivé du 1er code d'alarme (protobuf day_data, enum
    AlarmReason) ; à défaut du booléen cloud, message générique.
    """
    messages = ALARM_MESSAGES if messages is None else messages
    if not connect:
        return "Alerte", "Micro-onduleur hors ligne"
    if warn or codes:
        code = codes[0] if codes else None
        if code is not None:
            msg = messages.get(code, f"Alarme (code {code})")
        else:
            msg = "Anomalie détectée"
        return "Warning", msg
    # Sentinelle « OK » et non chaîne vide : le core Jeedom n'émet pas
    # d'événement pour une valeur vide (core/api/jeeApi.php : init('value') != '')
    # → les scénarios ne se déclencheraient jamais sur le retour à la normale.
    return "Normal", "OK"


def entry_ports(entry):
    """Ports MPPT réellement présents dans une entrée micro du protobuf
    day_data (ex. [1, 2] sur un HMS-1000-2WB, [1, 2, 3, 4] sur un 4 MPPT).

    Évite de pousser up3/ip3/e3 sur un micro qui n'a que deux entrées (ancien
    code : `if port not in (1, 2): continue` → les micros 4 MPPT étaient
    silencieusement tronqués à leurs deux premiers ports)."""
    ports = (entry or {}).get("ports") or {}
    out = []
    for p in ports:
        try:
            out.append(int(p))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def burst_delay_ms(server_dly, min_interval_s):
    """Délai avant le prochain cycle burst.

    Le serveur S-Miles impose son propre rythme via `dly` (1,5 à 10 s) : on le
    respecte, en gardant le réglage utilisateur (« Intervalle minimum burst »)
    comme plancher — sinon ce paramètre n'aurait aucun effet (il était stocké
    mais jamais lu jusqu'en 0.1.9)."""
    try:
        dly = int(server_dly)
    except (TypeError, ValueError):
        dly = 1500
    try:
        floor_ms = int(float(min_interval_s) * 1000)
    except (TypeError, ValueError):
        floor_ms = 2000
    return max(dly, floor_ms, 1000)
