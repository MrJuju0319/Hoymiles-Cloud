#!/bin/bash
# Hoymiles Cloud — installation des dépendances Python (venv local au plugin)
# S'exécute en root via le système de dépendances Jeedom (sudo).
set -e
cd "$(dirname "$0")"
PLUGIN_DIR="$(cd .. && pwd)"

echo "[hoymilescloud] Installation des dépendances..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet requests argon2-cffi
chown -R www-data:www-data "$PLUGIN_DIR" 2>/dev/null || true
echo "[hoymilescloud] OK — dépendances installées dans $PLUGIN_DIR/resources/venv"
