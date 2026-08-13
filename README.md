# Hoymiles Cloud

Plugin **Jeedom** de supervision des **micro-onduleurs Hoymiles** (HMS-xxx-WB/T) via le **cloud S-Miles**.

> ⚡ **Temps réel sans matériel local** : fonctionne uniquement via le cloud — pas besoin de gateway locale, de BLE ou de WiFi. Les valeurs sont poussées par burst (~2-3 s) comme l'app S-Miles.

---

## ✨ Fonctionnalités

- **Station** : puissance instantanée (`real_power`), production jour / mois / totale, taux d'autoconsommation, CO₂ évité, statut online
- **Micro-onduleurs** (par string PV) : puissance AC (`pac`), puissance par port PV (`p1`..`p4`), état connecté
- **Temps réel par burst** : mêmes endpoints que l'app S-Miles (burst `m:0` + `m:3`, rythme dicté par le serveur ~1,5-3 s)
- **Push intelligent vers Jeedom** : seuil de changement configurable pour ne pas noyer l'historique
- **Synchronisation cloud** : la station et les micros sont créés automatiquement en un clic
- **Contrôle du démon** : boutons dépendances / démon dans l'UI, supervision automatique (cron15), résilience aux coupures réseau (backoff exponentiel)

## 📦 Installation

1. **Market Jeedom** *(une fois publié)* : Plugins → Gestion des plugins → Market → rechercher « Hoymiles Cloud » → Installer
2. **Manuelle** : télécharger le zip, extraire dans `plugins/hoymilescloud/`, puis activer le plugin

Dépendances : Python 3 + venv (installées automatiquement au premier lancement — bouton « Dépendances »).

## ⚙️ Configuration

| Champ | Description |
|---|---|
| **Email S-Miles** | Identifiant du compte S-Miles (app S-Miles Home ou S-Miles Cloud) |
| **Mot de passe** | Mot de passe du compte S-Miles (stocké chiffré) |
| **Seuil de changement** | Différence minimale (W / Wh / %) pour pousser une valeur (1 par défaut) |

1. Renseigner les identifiants **S-Miles**
2. Cliquer sur **Tester la connexion** (vérifie l'authentification cloud)
3. Cliquer sur **Synchroniser les équipements** → création automatique de la Station + des micros
4. **Démarrer le démon** → les valeurs arrivent en temps réel

## 🔌 Commandes créées

**Station** : `real_power`, `today_eq`, `month_eq`, `total_eq`, `self_rate`, `co2`, `online`, `last_data_time`

**Micro-onduleur** : `pac`, `p1`, `p2`, `p3`, `p4`, `connect`, `soft_ver`

## 🛠️ Dépannage

| Problème | Solution |
|---|---|
| « Login failed » | Vérifier l'email/mot de passe S-Miles ; attention au **cooldown anti-brute-force** (~3-4 logins/minute depuis la même IP) |
| Le démon ne pousse plus les énergies | L'endpoint `count_station_real_data` applique un **rate-limit silencieux** après appels rapprochés : le démon réessaie au cycle suivant (60 s) et logge un warning |
| Burst ralenti | Normal : le serveur s'auto-régule (délai 1,5 s → 3 s) |

## 📚 Documentation

- [Documentation complète (fr)](docs/fr_FR/index.md)
- [Changelog](CHANGELOG.md)

## 🧩 API utilisée

- API interne **neapi.hoymiles.com** (S-Miles Home, Argon2id v3) — mêmes endpoints que l'app officielle
- API officielle **wapi.hoymiles.com** (statistiques, monitoring seul) — non utilisée pour le temps réel

## ⚖️ Licence

AGPL-3.0 — voir [LICENSE](LICENSE). Projet communautaire, non affilié à Hoymiles. Les marques Hoymiles et S-Miles appartiennent à leurs propriétaires respectifs.
