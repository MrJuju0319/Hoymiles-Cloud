<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom. */
try {
    require_once dirname(__FILE__) . '/../../core/php/core.inc.php';
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

    throw new Exception(__('Aucune méthode correspondante', __FILE__));
} catch (Exception $e) {
    ajax::error(displayException($e), $e->getCode());
}
