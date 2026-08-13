# Hoymiles Cloud — Documentation

Plugin Jeedom de supervision des **micro-onduleurs Hoymiles** (HMS-xxx-WB/T) via le **cloud S-Miles**.

- **Temps réel** : burst ~2-3 s (mêmes endpoints que l'app S-Miles)
- **Sans matériel local** : fonctionne même si la gateway BLE/WiFi locale est éteinte
- **Multi-micros** : station + tous les micro-onduleurs du compte

---

## 1. Prérequis

- Jeedom ≥ 4.4 (testé sur 4.6)
- Un **compte S-Miles** (celui de l'application S-Miles Home ou S-Miles Cloud) — les micro-onduleurs doivent déjà y être associés
- Python 3 + `venv` (installés automatiquement via le bouton **Dépendances**)

## 2. Installation

1. **Market** : `Plugins → Gestion des plugins → Market` → rechercher **Hoymiles Cloud** → **Installer**
2. Activation : `Plugins → Énergie → Hoymiles Cloud` → **Activer**
3. **Dépendances** : cliquer sur le bouton **Dépendances** (état passe à *OK* une fois le venv Python créé) — ou laisser l'installation automatique se faire

> Installation manuelle : télécharger le zip depuis GitHub, extraire dans `plugins/hoymilescloud/` sur le serveur Jeedom, puis activer le plugin.

## 3. Configuration

`Plugins → Énergie → Hoymiles Cloud → Configuration`

| Champ | Description |
|---|---|
| **Email S-Miles** | Identifiant du compte S-Miles (ex. votre adresse email) |
| **Mot de passe** | Mot de passe du compte S-Miles (stocké chiffré par Jeedom) |
| **Seuil de changement** | Différence minimale (W, Wh, %, valeur) pour pousser une valeur vers Jeedom — 1 par défaut |

### Étapes

1. Renseigner **Email** et **Mot de passe**
2. **Tester la connexion** → doit afficher « Connecté » avec le nom de la station
3. **Synchroniser les équipements** → crée automatiquement :
   - la **Station** (nom = nom de la station S-Miles)
   - un équipement par **micro-onduleur** (nom = modèle + n° de série)
4. **Démarrer le démon** (état du plugin) → les valeurs sont poussées en temps réel

## 4. Équipements et commandes

### Station (ex. « Mon domicile »)

| LogicalId | Nom | Unité | Description |
|---|---|---|---|
| `real_power` | Production instantanée | W | Puissance AC totale de la station (temps réel, burst) |
| `today_eq` | Production jour | Wh | Énergie du jour |
| `month_eq` | Production mois | Wh | Énergie du mois |
| `total_eq` | Production totale | Wh | Énergie cumulée |
| `self_rate` | Autoconsommation | % | Taux d'autoconsommation |
| `co2` | CO₂ évité | g | Émissions évitées |
| `online` | En ligne | binaire | 1 si la station est connectée au cloud |
| `last_data_time` | Dernière donnée | date | Horodatage de la dernière remontée de données |

### Micro-onduleur (ex. « HMS-1000-2WB (1610A38B34D5) »)

| LogicalId | Nom | Unité | Description |
|---|---|---|---|
| `pac` | Puissance AC | W | Puissance de sortie du micro |
| `p1` / `p2` / `p3` / `p4` | PV 1..4 | W | Puissance par port PV (2 ports sur les HMS-1000) |
| `connect` | Connecté | binaire | 1 si le micro répond (warn_data.connect) |
| `soft_ver` | Version firmware | texte | Version du firmware (info uniquement) |

> Les commandes peuvent être renommées, reclassées dans vos objets, et utilisées dans les **virtuels**, **scénarios**, **widgets** et **designs** comme n'importe quelle commande Jeedom.

## 5. Fonctionnement interne

- **Authentification** : Argon2id v3 (profil S-Miles Home, `euapi.hoymiles.com`) — même mécanisme que l'app officielle
- **Temps réel** : endpoints `data/burst` (`m:0` = station, `m:3` = micros) au rythme dicté par le serveur (~1,5-3 s)
- **Énergies/statut** : `count_station_real_data` toutes les 60 s
- **Push intelligent** : une valeur n'est poussée que si elle change de plus que le seuil configuré (évite de saturer l'historique)
- **Résilience** : après 3 échecs de burst, repli sur polling + backoff exponentiel ; re-login seulement si le token expire ; supervision automatique par cron15
- **Sécurité** : les identifiants ne quittent jamais le serveur (le daemon les lit dans la config Jeedom chiffrée)

## 6. FAQ / Dépannage

### « Échec de la connexion » au test
- Vérifier email + mot de passe S-Miles
- **Cooldown anti-brute-force** : après ~3-4 tentatives de login rapprochées, S-Miles refuse temporairement (~5-10 min). Attendre puis réessayer.

### Le démon tourne mais les énergies ne bougent pas
- L'endpoint `count_station_real_data` applique un **rate-limit silencieux** après appels trop rapprochés depuis la même IP : le démon logge un warning et réessaie au cycle suivant (60 s). Le temps réel (puissance) n'est jamais affecté.
- Vérifier `log/hoymilescloud_daemon` (via Réglages → Logs) : « Slow poll : réponse vide » indique le rate-limit.

### La page du plugin affiche « Aucune méthode correspondante »
- Vider le cache Jeedom (`Réglages → Système → Cache`) après une mise à jour du plugin.

### Le plugin est-il affilié à Hoymiles ?
Non — projet communautaire indépendant. Les marques Hoymiles / S-Miles appartiennent à leurs propriétaires.

## 7. Limitations connues

- **Contrôle** (limitation de puissance, arrêt) : non exposé dans cette version (l'API utilisée est en lecture). Une API officielle de contrôle existe chez Hoymiles mais n'est pas encore intégrée.
- **Historique cloud** : les statistiques longues (15 jours par micro) nécessitent la clé API officielle (wapi.hoymiles.com) — prévu dans une version ultérieure.
- L'application S-Miles et ce plugin partagent le même compte : les sessions simultanées sont tolérées.

---

*Projet communautaire, non affilié à Hoymiles. Licence AGPL-3.0.*
