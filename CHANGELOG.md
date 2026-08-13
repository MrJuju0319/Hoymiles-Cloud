# 📜 Changelog — Hoymiles Cloud

Le projet suit un workflow **bêta → stable** : les nouveautés arrivent sur la branche `beta`, sont testées en conditions réelles, puis passent sur `stable` après validation.

---

## ✅ Version STABLE — 0.1.8 (2026-08-13)

> ✔️ **Validée par Julien** — toute la série 0.1.1 → 0.1.8 est passée sur la branche `stable` (0.1.0 → 0.1.8). Résumé en une ligne par version (détails plus bas).

- **0.1.1 — Fiabilité** : fix de l'« erreur réseau » (chemins `require_once` corrigés)
- **0.1.2 — Non destructif** : la synchronisation ne renomme plus vos équipements/commandes personnalisés
- **0.1.3 — Production annuelle** : commande `year_eq` + commande d'alerte `warn` par micro
- **0.1.4 — Données électriques complètes** : tensions, courants, fréquence et température par micro (protobuf `down_module_day_data`) + documentation complète
- **0.1.5 — Démon fiable** : 4 threads + file d'attente (plus aucun blocage réseau), zéro écriture disque en fonctionnement, heartbeat, panneau d'état live sur la page du plugin
- **0.1.6 — Sécurité** : identifiants chiffrés (`crypt:` + perms 0600), commandes shell protégées (`escapeshellarg`), dépendances épinglées, audit AJAX
- **0.1.7 — Santé des micros** : commandes `Statut` (Normal / Warning / Alerte) et `Message d'erreur` en français pour chaque micro — exploitable par les scénarios
- **0.1.8 — Anti-valeurs fantômes** : micro hors ligne > 5 min → V/A/W/Hz forcés à 0 (comportement nuit) + fix du burst nocturne (plus de faux mode dégradé)

---

## 🧪 Version BÊTA — 0.1.4 (2026-08-13)

> ✔️ Historique validé (13/08/2026) — passé sur la branche `stable`.

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

> ✔️ Historique validé (13/08/2026) — passé sur la branche `stable`.

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


---

## 🧪 Version BÊTA — 0.1.6 (2026-08-13)

> ✔️ Historique validé (13/08/2026) — passé sur la branche `stable`.

### 🔒 Audit sécurité (4 points, demandé par Julien)

- **Identifiants et logs** : le mot de passe S-Miles n'est plus jamais écrit en clair dans le fichier runtime `/tmp/jeedom/hoymilescloud/config.json` — il est chiffré (`utils::encrypt()` → `crypt:...`, AES-256-CBC + HMAC avec la clé `data/jeedom_encryption.key`) et déchiffré côté daemon via `jeedom_decrypt()` (openssl, HMAC vérifié). Rétrocompat : les anciennes configs en clair continuent de fonctionner. **Permissions durcies** : config.json en `0600` (www-data uniquement), dossier runtime en `0750`. Le mot de passe ne transite jamais dans les logs (vérifié par grep).
- **Exécution de commandes** : la commande de lancement du démon (`deamon_start()`) passe désormais chaque élément par `escapeshellarg()` — aucune injection de commande possible. `deamon_stop()` utilisait déjà `escapeshellarg()`.
- **AJAX** : audit du modèle — déjà blindé (session Jeedom → rôle admin → `ajax::init()` anti-CSRF → whitelist d'actions explicite → aucun SQL brut, tout passe par l'ORM). Documenté en tête de `hoymilescloud.ajax.php`.
- **Dépendances** : `requirements.txt` épinglé (`requests>=2.32.3` — CVE réseau corrigées en 2.32.x ; `argon2-cffi>=23.1.0`). Venv à jour : requests 2.34.2, argon2-cffi 25.1.0.


---

## 🧪 Version BÊTA — 0.1.7 (2026-08-13)

> ✔️ Historique validé (13/08/2026) — passé sur la branche `stable`.

### ❤️ Santé des micro-onduleurs (Statut + Message d'erreur)

Nouveau : chaque micro-onduleur remonte son **état de santé** dans Jeedom, exploitable par les scénarios et l'IA native.

- **2 nouvelles commandes info par micro** :
  - `status` (Statut, string) : **`Normal` / `Warning` / `Alerte`**
  - `alarm_msg` (Message d'erreur, string) : détail en français — ex. « Surtension réseau (grid over voltage) », « Sur-température (over-temperature) » ; `OK` si Normal
- **Sources** : `warn_data` (`select_by_station` avec `show_warn=1` — obligatoire, sinon warn_data est vide) + **codes d'alarme du protobuf** `down_module_day_data` (champs int16 par bucket, enum AlarmReason du protocole DTU → `alarm_codes` décodés dans `parse_day_data`)
- **Logique de sévérité** : micro hors ligne (`connect=false`) → **Alerte** « Micro-onduleur hors ligne » ; anomalie signalée (`warn=true` ou codes présents) → **Warning** + message du 1er code ; sinon → **Normal** / `OK`
- Le push jeeApi (type=cmd) **lève l'événement Jeedom** → les scénarios se déclenchent automatiquement
- Sentinelle `OK` (et non chaîne vide) : le core Jeedom ignore les valeurs vides (`core/api/jeeApi.php` l.114 : `init('value') != ''`)
- **Unités** : audit complet — toutes les commandes numériques ont leur unité (V, A, Hz, °C, W, Wh, %, g)

---

## 🧪 Version BÊTA — 0.1.8 (2026-08-13)

> ✔️ Historique validé (13/08/2026) — passé sur la branche `stable`.

### 🌙 Valeurs forcées à 0 quand un micro est hors ligne (demandé par Julien)

Un micro-onduleur déconnecté laissait ses **dernières valeurs figées** dans Jeedom (ex. 344 W affichés alors qu'il est mort) — les scénarios pouvaient réagir à une production fantôme. Désormais :

- **Délai de grâce 5 min** (`OFF_LINE_DELAY = 300` s) : passé ce délai sans `connect` cloud, toutes les **commandes électriques** du micro sont **forcées à 0** (comportement « pleine nuit ») : `uac`, `up1`, `up2` (V), `ip1`, `ip2` (A), `freq` (Hz), `pac`, `p1`-`p4` (W)
- **Station** : `real_power` forcée à 0 **seulement si tous les micros** sont hors ligne (on ne masque jamais la production des micros sains)
- **`temp` volontairement exclue** : valeur thermique, pas électrique — en pleine nuit la température interne du micro ne tomberait pas à 0
- **Source fiable** : suit le flag cloud `connect` (`warn_data`, `show_warn=1`) — la **même source que le statut « Alerte »** ; une coupure de l'API S-Miles (réseau local, rate-limit) ne déclenche **jamais** de faux zéro
- **Retour en ligne** : les valeurs réelles reviennent automatiquement (puissances immédiatement via le burst, V/A au prochain cycle « données jour » ≤ 5 min)
- **Zéro spam** : le push intelligent ne re-pousse 0 qu'aux changements réels ; logs de franchissement limités
- **Fix nuit** : « Pas d'URI burst » quand la station ne produit plus (nuit) n'est **plus** traité comme une panne — log espacé (1×/10 min), nouvel essai toutes les 5 min, plus de faux « mode dégradé » ni de spam de logs
- **Tests unitaires** : 6 scénarios (micro hors ligne / fraîchement coupé / station partielle / retour / None / temp) — tous verts avant déploiement
