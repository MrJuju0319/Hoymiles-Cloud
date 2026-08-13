# ☀️ Hoymiles Cloud

> **Plugin Jeedom** de supervision des **micro-onduleurs Hoymiles** (HMS-xxx-WB / -T) via le **cloud S-Miles**.

⚡ **Temps réel sans matériel local** : le plugin interroge le même cloud que l'application S-Miles — **aucune gateway locale, aucun BLE, aucun WiFi à configurer**. Fonctionne même si tes micro-onduleurs sont inaccessibles en local.

---

## ✨ Fonctionnalités

| | |
|---|---|
| ⚡ **Temps réel** | Puissance station + par micro, burst ~2-3 s (mêmes endpoints que l'app) |
| 📊 **Énergies** | Production jour / mois / **année** / totale, autoconsommation, CO₂ évité |
| 🔌 **Électrique** | **Tensions PV par port** (V), **courants PV** (A), **tension réseau** (V), **fréquence** (Hz), **température du micro** (°C) |
| 🚨 **Alertes** | État connecté + alerte anomalie par micro |
| 🤖 **Automatique** | Synchronisation cloud en 1 clic (station + tous les micros), démon auto-surveillé |
| 🧠 **Push intelligent** | Seuil de changement configurable : l'historique Jeedom n'est pas noyé |
| 🔒 **Sécurisé** | Identifiants stockés chiffrés par Jeedom, jamais en dur, ne quittent pas le serveur |
| 🌍 **Multi-langue** | Français, English |

---

## 📋 Prérequis

- **Jeedom ≥ 4.4** (testé sur 4.6.1)
- Un **compte S-Miles** (application S-Miles Home ou S-Miles Cloud) avec vos micro-onduleurs **déjà associés** (c'est le compte de l'app que vous utilisez déjà)
- **Python 3** + `venv` (installés automatiquement par le bouton **Dépendances**)
- Le serveur Jeedom doit pouvoir joindre `euapi.hoymiles.com` / `neapi.hoymiles.com` (sortie HTTPS 443)

---

## 📦 Installation

### Option A — Market Jeedom *(une fois publié)*

1. `Plugins → Gestion des plugins → Market`
2. Rechercher **Hoymiles Cloud** → **Installer**
3. Activer le plugin

### Option B — Installation manuelle

1. Télécharger la dernière version stable depuis les [releases GitHub](https://github.com/MrJuju0319/Hoymiles-Cloud/releases) (ou la branche `beta` pour tester les nouveautés)
2. Extraire le contenu dans `plugins/hoymilescloud/` sur le serveur Jeedom
3. `Plugins → Énergie → Hoymiles Cloud` → **Activer**

### Option C — Depuis GitHub

```bash
cd /var/www/html/plugins
git clone -b stable https://github.com/MrJuju0319/Hoymiles-Cloud.git hoymilescloud
# puis activer le plugin dans l'interface Jeedom
```

### Dépendances

1. Ouvrir la page du plugin
2. Cliquer **Dépendances** → l'état passe à *OK* quand le venv Python est prêt (ou laisser l'installation automatique au premier lancement)

---

## ⚙️ Configuration

`Plugins → Énergie → Hoymiles Cloud → Configuration`

| Champ | Description |
|---|---|
| **Email S-Miles** | Identifiant de votre compte S-Miles (adresse email) |
| **Mot de passe** | Mot de passe du compte S-Miles (chiffré par Jeedom) |
| **Seuil de changement** | Différence minimale (W, Wh, %, …) pour pousser une valeur vers Jeedom — `1` par défaut |

### Étapes pas à pas

```mermaid
graph LR
    A[1. Renseigner email + mot de passe] --> B[2. Tester la connexion]
    B --> C[3. Synchroniser les équipements]
    C --> D[4. Démarrer le démon]
    D --> E[✅ Données en temps réel]
```

1. **Renseigner** l'email et le mot de passe S-Miles
2. Cliquer **Tester la connexion** → toast vert *« Connecté (v3/home). N station(s) trouvée(s) : … »*
3. Cliquer **Synchroniser** → création automatique :
   - la **Station** (nom = nom de la station dans S-Miles, ex. « Mon domicile »)
   - un **équipement par micro-onduleur** (ex. « HMS-1000-2WB (1610A38B350B) »)
4. **Démarrer le démon** → les valeurs sont poussées en continu

> 🎨 **Personnalisation libre** : renommez équipements et commandes comme vous voulez (« Balcon Sud », « Garage »…) — **la synchronisation ne re-renomme jamais** ce que vous avez personnalisé (les noms cloud ne sont appliqués qu'à la création).

---

## 🏠 Équipements & commandes

### Station (ex. « Mon domicile »)

| LogicalId | Nom | Unité | Source | Description |
|---|---|---|---|---|
| `real_power` | Production instantanée | W | burst ~2-3 s | Puissance AC totale de la station |
| `today_eq` | Production jour | Wh | 60 s | Énergie du jour |
| `month_eq` | Production mois | Wh | 60 s | Énergie du mois |
| `year_eq` | Production année | Wh | 60 s | Énergie de l'année en cours |
| `total_eq` | Production totale | Wh | 60 s | Énergie cumulée |
| `self_rate` | Autoconsommation | % | burst + 60 s | Taux d'autoconsommation |
| `co2` | CO₂ évité | g | 60 s | Émissions évitées |
| `online` | En ligne | binaire | 60 s | 1 si la station répond |
| `last_data_time` | Dernière donnée | date | 60 s | Dernière remontée du cloud |

### Micro-onduleur (ex. « HMS-1000-2WB (…) »)

| LogicalId | Nom | Unité | Source | Description |
|---|---|---|---|---|
| `pac` | Puissance AC | W | burst ~2-3 s | Puissance de sortie du micro |
| `p1` / `p2` / `p3` / `p4` | PV 1..4 | W | burst ~2-3 s | Puissance par port PV (2 ports sur les HMS-1000) |
| `up1` / `up2` | Tension PV 1/2 | V | 5 min | **Tension DC du panneau** (grain graphique app) |
| `ip1` / `ip2` | Courant PV 1/2 | A | 5 min | **Courant DC du panneau** |
| `uac` | Tension réseau | V | 5 min | Tension AC |
| `freq` | Fréquence réseau | Hz | 5 min | Fréquence AC |
| `temp` | Température micro | °C | 5 min | Température interne du boîtier |
| `warn` | Alerte | binaire | 60 s | 1 si le micro signale une anomalie |
| `connect` | Connecté | binaire | burst | 1 si le micro répond au burst |
| `soft_ver` | Firmware | texte | synchro | Version du firmware (info) |

> Toutes les commandes sont utilisables dans les **virtuels, scénarios, widgets, designs** comme n'importe quelle commande Jeedom, avec historique et graphiques.

---

## 🔬 Fonctionnement interne

### Architecture

```
┌──────────────────────────┐        ┌─────────────────────────────────────────┐
│    Cloud S-Miles         │        │         Serveur Jeedom                  │
│  (Hoymiles, Chine/EU)    │        │                                         │
│                          │ HTTPS   │  ┌─────────────────────────────────┐   │
│  euapi.hoymiles.com      │◄───────┼─►│  hoymiles_daemon.py (venv)       │   │
│  neapi.hoymiles.com      │        │  │  • burst m:0 + m:3  (~2-3 s)     │   │
│  eurt.hoymiles.com (rds) │        │  │  • count_station_real_data (60s) │   │
│                          │        │  │  • down_module_day_data (5 min)  │   │
│  Authentification :      │        │  └──────────────┬──────────────────┘   │
│  Argon2id v3             │        │                 │ jeeApi.php (push)    │
└──────────────────────────┘        │  ┌──────────────▼──────────────────┐   │
                                    │  │        Plugin hoymilescloud     │   │
                                    │  │  équipements + commandes        │   │
                                    │  │  (station + micros)             │   │
                                    │  └─────────────────────────────────┘   │
                                    └─────────────────────────────────────────┘
```

### Les 3 boucles de collecte

| Boucle | Fréquence | Endpoint | Données |
|---|---|---|---|
| **Burst temps réel** | ~1,5-3 s (rythme dicté par le serveur `dly`) | `data/burst` m:0 + m:3 | Puissance station, autoconsommation, puissance par micro et par port |
| **Polling lent** | 60 s | `count_station_real_data` | Énergies jour/mois/année/total, CO₂, statut, alerte micro |
| **Données jour** | 5 min | `down_module_day_data` (protobuf) | **Tensions PV, courants PV, tension réseau, fréquence, température** — grain identique aux graphiques de l'app S-Miles |

### Push intelligent

Une valeur n'est **poussée vers Jeedom** que si elle change de plus que le **seuil configuré** (1 par défaut) depuis la dernière poussée. Les valeurs stables (ex. énergie du jour qui n'évolue pas) ne génèrent donc **aucun trafic ni entrée d'historique inutile**.

### Authentification

- Profil **S-Miles Home** (compte bricoleur/balcon) : **Argon2id v3** sur `euapi.hoymiles.com` avec l'User-Agent `sma/ad/2.10.0/159/0` (obligatoire)
- Token valide ~2 h, renouvelé automatiquement par le démon **uniquement** sur expiration ou `status=100` (les re-logins inutiles déclencheraient le cooldown anti-brute-force)

### Résilience

- **3 échecs de burst** → repli automatique sur le polling seul (mode dégradé) + backoff exponentiel
- **Rate-limit silencieux** de `count_station_real_data` (réponses vides temporaires) → warning au log, retry au cycle suivant — le temps réel n'est jamais affecté
- **Cooldown login** (~3-4/min) → le démon ne relogine jamais en boucle
- **Supervision** : cron15 Jeedom surveille le démon et le relance si nécessaire
- **Re-synchronisation** : le démon recharge la config à chaque cycle si vous ajoutez des équipements

### API utilisée (récapitulatif)

| Endpoint | Rôle |
|---|---|
| `iam/pub/3/auth/pre-insp` + `auth/login` | Authentification Argon2id v3 |
| `pvm/api/0/station/select_by_page` | Liste des stations du compte |
| `pvm/api/0/station/get_sd_uri` | Obtention de l'URI burst |
| `data/burst` (eurt.hoymiles.com) | Temps réel (puissances) |
| `pvm-data/api/0/station/data/count_station_real_data` | Énergies + statut |
| `pvm-data/api/0/module/data/down_module_day_data` | **Protobuf** tensions/courants/température |
| `pvm/api/0/dev/micro/select_by_station` | Micros, alertes, versions |
| `pvm/api/0/station/select_device_of_tree` | Arbre DTU → micros |

> ⚠️ L'API est **non officielle** (rétro-ingénierie communautaire). Elle peut évoluer sans préavis ; le plugin est conçu pour tolérer les réponses vides et les changements de rythme.

---

## ❓ FAQ / Dépannage

### « Échec de la connexion » au test de connexion
- Vérifiez email + mot de passe S-Miles
- **Cooldown anti-brute-force** : après ~3-4 tentatives rapprochées, S-Miles refuse le login ~5-10 min. Attendez, puis réessayez.

### Le démon tourne mais les énergies ne bougent pas
- `count_station_real_data` a un **rate-limit silencieux** : `Réglages → Logs → hoymilescloud_daemon`, si vous voyez « Slow poll : réponse vide », c'est normal — nouvel essai au cycle suivant (60 s). La puissance temps réel n'est jamais affectée.

### Tension/courant/température à 0 ou absents
- Ces données sont en **buckets de 5 min** : elles n'apparaissent que quelques minutes après le démarrage du démon (premier fetch 30 s après le démarrage, puis toutes les 5 min).
- La nuit ou sans soleil, les valeurs sont cohérentes avec le micro (tension réseau ~230 V, fréquence ~50 Hz, production 0).

### La page du plugin affiche « Aucune méthode correspondante »
- Vider le cache : `Réglages → Système → Cache` après une mise à jour.

### Je peux renommer mes équipements ?
- **Oui, sans risque** : la synchro n'applique le nom cloud qu'à la création (v0.1.2+).

### Le plugin est-il affilié à Hoymiles ?
- **Non** — projet communautaire indépendant, non affilié. Les marques Hoymiles / S-Miles appartiennent à leurs propriétaires.

---

## 🧪 Versions — Bêta vs Stable

Le projet suit un **workflow de publication en 2 branches** :

| Branche | Usage | Version actuelle |
|---|---|---|
| `stable` / `master` | **Production** — validée par Julien après tests réels | **0.1.0** |
| `beta` | **Tests** — nouvelles fonctionnalités, corrections | **0.1.4** |

- Les **nouveautés arrivent toujours sur `beta`** et sont testées en conditions réelles (production réelle de la maison)
- Une version passe sur `stable` **uniquement après validation** sur le terrain
- Le **Market Jeedom** proposera la branche `stable` par défaut ; les curieux peuvent tester `beta` via GitHub

### Comment tester la bêta

```bash
cd /var/www/html/plugins
mv hoymilescloud hoymilescloud.stable   # sauvegarde de la version stable
git clone -b beta https://github.com/MrJuju0319/Hoymiles-Cloud.git hoymilescloud
# vider le cache Jeedom, puis re-tester
```

> ⚠️ En cas de souci : supprimez le dossier `hoymilescloud` et renommez `hoymilescloud.stable` → `hoymilescloud`.

### Changelog

📜 **Changelog complet et détaillé : [CHANGELOG.md](CHANGELOG.md)**

---

## ⚠️ Limitations connues

- **Contrôle** (limitation de puissance, arrêt/relance) : non exposé dans cette version — l'API utilisée est en **lecture seule**. Une API de contrôle existe chez Hoymiles mais n'est pas encore intégrée (prévu).
- **Température des panneaux** : les micros HMS n'ont **aucun capteur de température de surface** — seul le boîtier interne est mesuré (`temp`). Pour la température des panneaux : capteur dédié ou API météo.
- **Historique cloud long** (15 jours par micro) : nécessite la clé API officielle (wapi.hoymiles.com) — prévu dans une version ultérieure.
- L'app S-Miles et le plugin partagent le même compte : les sessions simultanées sont tolérées.

---

## 📄 Licence

**AGPL-3.0** — projet communautaire indépendant, non affilié à Hoymiles. Les marques **Hoymiles** et **S-Miles** appartiennent à leurs propriétaires respectifs.

*Développé avec ❤️ par Julien et une IA.*
