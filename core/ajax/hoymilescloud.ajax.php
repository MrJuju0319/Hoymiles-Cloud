<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 *
 * SÉCURITÉ (audit 13/08/2026) — modèle de défense en profondeur :
 * 1. include_file('core', 'authentification')  → session utilisateur Jeedom obligatoire
 * 2. isConnect('admin')                        → réservé au rôle admin (401 sinon)
 * 3. ajax::init()                              → jeton CSRF ajax vérifié par le core
 * 4. Whitelist d'actions explicite             → aucun routage dynamique de paramètres
 * 5. Aucun SQL brut : tout passe par l'ORM (eqLogic::byType/getCmd/getCache)
 *    → aucune surface d'injection SQL (CWE-89)
 * 6. Aucune action n'accepte de paramètre utilisateur (init() hors 'action')
 *    → pas de surface d'injection de commande côté PHP
 */
try {
    require_once dirname(__FILE__) . '/../../../../core/php/core.inc.php';
    include_file('core', 'authentification', 'php');

    if (!isConnect('admin')) {
        throw new Exception(__('401 - Accès non autorisé', __FILE__));
    }

    ajax::init();

    if (init('action') == 'testConnection') {
        $result = hoymilescloud::testConnection();
        ajax::success($result);
    }

    if (init('action') == 'syncFromCloud') {
        $result = hoymilescloud::syncFromCloud();
        ajax::success($result);
    }

    if (init('action') == 'getStatus') {
        $result = hoymilescloud::getDaemonStatus();
        ajax::success($result);
    }

    throw new Exception(__('Aucune méthode correspondante', __FILE__));
} catch (Exception $e) {
    ajax::error(displayException($e), $e->getCode());
}
