"""Ajout du dossier resources/ au chemin d'import des tests.

Les modules testés (hoymiles_logic, hoymiles_api, backfill) s'importent comme
le fait le démon : depuis resources/. Aucun test n'ouvre de connexion réseau —
le blob protobuf est construit par tests/pbgen.py.
"""
import os
import sys

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources")
if RESOURCES not in sys.path:
    sys.path.insert(0, RESOURCES)
