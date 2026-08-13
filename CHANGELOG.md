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

## 0.1.1 (2026-08-13)

- **Fix critique** : chemins `require_once` relatifs corrigés (`core/ajax/hoymilescloud.ajax.php` et `plugin_info/install.php`) — l'activation/la page de configuration renvoyaient une erreur réseau (500) car `core.inc.php` n'était pas trouvé.

## 0.1.2 (2026-08-13)

- **Amélioration** : la synchronisation ne renomme plus les équipements ni les commandes déjà personnalisés — le nom cloud n'est appliqué qu'à la création.
