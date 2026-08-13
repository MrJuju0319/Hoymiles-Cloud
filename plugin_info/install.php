<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 * Called on plugin install/update — builds the Python venv for the daemon.
 */
require_once dirname(__FILE__) . '/../../../core/php/install_jeedom.php';

try {
    $plugin_dir = realpath(dirname(__FILE__) . '/..');
    $res_dir = $plugin_dir . '/resources';
    $log = log::getPathToLog('hoymilescloud_update');

    $cmd = 'bash ' . $res_dir . '/install.sh >> ' . $log . ' 2>&1';
    exec($cmd . ' &');
    log::add('hoymilescloud', 'info', 'Installation des dépendances lancée (venv Python)');
} catch (Exception $e) {
    log::add('hoymilescloud', 'error', 'Erreur install: ' . $e->getMessage());
}
