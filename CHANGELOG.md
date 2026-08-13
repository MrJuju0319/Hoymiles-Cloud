# 📜 Changelog — Hoymiles Cloud

Le projet suit un workflow **bêta → stable** : les nouveautés arrivent sur la branche `beta`, sont testées en conditions réelles, puis passent sur `stable` après validation.

---

## 🧪 Version BÊTA — 0.1.4 (2026-08-13)

> Branche `beta` — **en cours de test**, non validée pour la production.

### 0.1.4 — Nouvelles commandes électriques (tensions, courants, températures)

Découverte majeure : le cloud expose **toutes** les données électriques via l'endpoint `down_module_day_data` (protobuf, buckets de 5 min — le même grain que les graphiques de l'app S-Miles).

- **Nouvelles commandes par micro-onduleur** :
  - `up1` / `up2` : **tension DC** par port PV (V)
  - `ip1` / `ip2` : **courant DC** par port PV (A)
  - `uac` : **tension réseau** (V)
  - `freq` : **fréquence réseau** (Hz)
  - `temp` : **température interne** du micro (°C)
- **Démon** : nouvelle boucle « données jour » toutes les 5 min (`day_data_interval` configurable), premier fetch 30 s après le démarrage
- **Parseur protobuf maison** dans `hoymiles_api.py` (`_pb_parse` / `parse_day_data`) — zéro dépendance ajoutée
- Push intelligent sur ces valeurs (seuil serré 0,1 : elles bougent peu entre 2 buckets)
- Documentation enrichie (README + docs fr/en)

### 0.1.3 — Production annuelle + alertes micro

- **Nouveauté** : commande `year_eq` (production annuelle, station)
- **Nouveauté** : commande `warn` (alerte anomalie par micro-onduleur, `warn_data.warn`)
- Les deux poussées toutes les 60 s (polling lent)

### 0.1.2 — Synchronisation non destructive

- **Amélioration** : la synchronisation ne renomme **plus** les équipements ni les commandes personnalisés par l'utilisateur — le nom cloud n'est appliqué qu'à la **création**
- Testé en conditions réelles : « Ma Station Perso » et « Puissance perso » préservés après synchronisation

### 0.1.1 — Fix critique « Erreur réseau »

- **Fix critique** : chemins `require_once` relatifs corrigés (`core/ajax/hoymilescloud.ajax.php` → 4 niveaux, `plugin_info/install.php` → 3 niveaux)
- L'activation / le test de connexion / la synchronisation renvoyaient une erreur réseau (500 silencieux) car `core.inc.php` n'était pas trouvé

---

## ✅ Version STABLE — 0.1.0 (2026-08-13)

> Branche `stable` / `master` — **validée** : supervision complète en conditions réelles (production, temps réel, énergies).

- **Plugin** : supervision des micro-onduleurs Hoymiles HMS-xxx-WB/T via le cloud S-Miles (API neapi.hoymiles.com, profil S-Miles Home)
- **Temps réel** : burst `m:0` + `m:3` (~2-3 s) — puissance station + micros par string PV
- **Énergies** : production jour / mois / totale, autoconsommation, CO₂ évité, statut (poll 60 s)
- **Push intelligent** : seuil de changement configurable (1 par défaut) pour ne pas saturer l'historique
- **Synchronisation** : création automatique des équipements station + micros (nom appliqué à la création)
- **Démon** : venv Python local, supervision cron15, backoff exponentiel, re-login automatique uniquement sur expiration du token
- **UI** : page desktop moderne (plugin.template.js), boutons dépendances/démon, test de connexion, synchronisation
- **Multi-langue** : fr_FR, en_US
- **Sécurité** : identifiants chiffrés par Jeedom, jamais en dur dans le code

---

## 🗺️ Feuille de route

- [ ] **Contrôle** : limitation de puissance (%), arrêt/relance des micros (API de contrôle Hoymiles)
- [ ] **Clé API officielle** : historique cloud long (15 jours par micro) via wapi.hoymiles.com
- [ ] **Publication Market** : soumission sur market.jeedom.com
- [ ] **Tableau de bord** : widgets dédiés station + micros

---

*Projet communautaire indépendant, non affilié à Hoymiles. Licence AGPL-3.0.*

---

## 🧪 Version BÊTA — 0.1.5 (2026-08-13)

> Branche `beta` — **en cours de test**, non validée pour la production.

### Optimisation du démon (threads + file d'attente)

- **3 threads collecteurs indépendants** (burst ~2-3 s / slow 60 s / day 5 min) + **1 thread pusher** qui consomme une `queue.Queue` : un blocage réseau ne fige plus jamais le démon, chaque boucle garde son rythme.
- **Timeouts stricts partout** : API ≤ 10 s (`HTTP_TIMEOUT`), day_data 15 s, push Jeedom 10 s.
- **Zéro écriture disque en fonctionnement normal** (important carte SD Raspberry Pi) : cache des valeurs 100 % en mémoire, pid file 1× au démarrage, `status.json` écrit uniquement sur **changement d'état** (écriture atomique via `.tmp` + `rename`), relecture config plafonnée à 1×/5 s.

### Fiabilité et authentification

- **Auto-refresh token complet** : tout appel répondant `status=100` (token expiré) déclenche re-login + retry — y compris le **burst** (nouveau). Le login est **verrouillé par lock** (thread-safe, pas de double login → pas de cooldown).
- **Commande `daemon` (Démon OK)** sur la station : heartbeat binaire poussé **en force** toutes les 60 s (contourne le push intelligent) → un scénario Jeedom peut alerter si la commande n'est plus mise à jour depuis X minutes.
- **`status.json`** publié par le démon : état (ok/dégradé/arrêté), burst/slow/day OK, dernière donnée, erreur.

### Interface et ergonomie

- **Panneau « État du cloud S-Miles »** sur la page du plugin : badges démon/cloud, puissance, production jour, autoconsommation, dernière donnée, heartbeat — **rafraîchi en AJAX toutes les 15 s** (+ bouton Actualiser) sans recharger la page.
- Nouvelle action ajax `getStatus` → `getDaemonStatus()`.
- **Fix** : méthode renommée `getDaemonStatus` (le core Jeedom définit déjà `eqLogic::getStatus()` — une redéclaration statique causait un fatal silencieux au chargement de la classe).
- **Fix** : chemin ajax corrigé (`plugins/hoymilescloud/core/ajax/...`) — l'URL relative résolvait vers 404.
