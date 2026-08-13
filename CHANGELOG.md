# Changelog — Hoymiles Cloud

## 0.1.0 (2026-08-13)

Première version publiée.

- **Plugin** : supervision des micro-onduleurs Hoymiles HMS-xxx-WB/T via le cloud S-Miles (API neapi.hoymiles.com, profil S-Miles Home)
- **Temps réel** : burst `m:0` + `m:3` (~2-3 s) — puissance station + micros par string PV
- **Énergies** : production jour/mois/totale, autoconsommation, CO₂ évité, statut (poll 60 s)
- **Push intelligent** : seuil de changement configurable (1 par défaut)
- **Synchronisation** : création automatique des équipements station + micros
- **Démon** : venv Python local, supervision cron15, backoff exponentiel, re-login automatique
- **UI** : page desktop moderne (plugin.template.js), boutons dépendances/démon, test de connexion, synchro
- **Multi-langue** : fr_FR, en_US
