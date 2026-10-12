#!/bin/bash
# Hoymiles Cloud — installation des dépendances Python (venv local au plugin)
# S'exécute en root via le système de dépendances Jeedom (sudo).
set -e
cd "$(dirname "$0")"
PLUGIN_DIR="$(cd .. && pwd)"

# Barre de progression Jeedom : dependancy_info()['progress_file'] pointe sur ce
# fichier — sans écriture ici, l'interface reste bloquée sans indiquer
# l'avancement (et checkDeamon peut croire l'installation en cours pour toujours).
PROGRESS="/tmp/jeedom_install_in_progress_hoymilescloud"
progress() { echo "$1" > "$PROGRESS" 2>/dev/null || true; }
cleanup() { rm -f "$PROGRESS" 2>/dev/null || true; }
trap cleanup EXIT

progress 5
echo "[hoymilescloud] Installation des dépendances..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
progress 30
./venv/bin/pip install --quiet --upgrade pip
progress 60
# Versions minimales épinglées dans requirements.txt (requests < 2.32.0 : CVE
# réseau connues ; argon2-cffi récent requis pour l'auth Argon2id v3 S-Miles).
./venv/bin/pip install --quiet -r requirements.txt
progress 90
chown -R www-data:www-data "$PLUGIN_DIR" 2>/dev/null || true
progress 100
echo "[hoymilescloud] OK — dépendances installées dans $PLUGIN_DIR/resources/venv"
