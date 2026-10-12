<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 *
 * Appelé par le core (plugin::callInstallFunction) avec les fonctions
 * hoymilescloud_install / hoymilescloud_update / hoymilescloud_remove.
 *
 * ⚠️ Les crons du plugin DOIVENT être enregistrés ici : sans enregistrement,
 * le core n'appelle JAMAIS hoymilescloud::cron5()/cron15() — l'ingestion du
 * backfill historique et le watchdog du démon ne tournaient pas du tout
 * (constat : aucune ligne `hoymilescloud` dans la table `cron` en 0.1.9).
 *
 * Note : l'ancienne version faisait require_once de
 * ../../../core/php/install_jeedom.php — ce fichier n'existe pas dans
 * Jeedom 4.6 (fatal error selon le contexte d'appel). On n'inclut le core
 * que si nécessaire (appel direct hors contexte core).
 */

if (!class_exists('cron')) {
    require_once dirname(__FILE__) . '/../../../core/php/core.inc.php';
}

function hoymilescloud_install()
{
    hoymilescloud_update(false);
}

function hoymilescloud_update($_direct = true)
{
    // ---------- Crons ----------
    // cron5  : ingestion du backfill.json (idempotent, fichier supprimé après)
    // cron15 : watchdog du démon (le core relance déjà via checkDeamon, ceci
    //          reste un filet de sécurité + ingestion de secours)
    $crons = array(
        'cron5' => '*/5 * * * *',
        'cron15' => '*/15 * * * *',
    );
    foreach ($crons as $function => $schedule) {
        $cron = cron::byClassAndFunction('hoymilescloud', $function);
        if (!is_object($cron)) {
            $cron = new cron();
            $cron->setClass('hoymilescloud');
            $cron->setFunction($function);
        }
        $cron->setSchedule($schedule);
        $cron->setTimeout(5);
        $cron->setEnable(1);
        $cron->save();
        log::add('hoymilescloud', 'info', 'Cron ' . $function . ' enregistré (' . $schedule . ')');
    }

    // ---------- Dépendances Python ----------
    // Uniquement si le venv est absent : une mise à jour de plugin ne doit pas
    // relancer une installation de dépendances (l'utilisateur garde le bouton
    // « Relancer » de Jeedom, et checkDeamon le fait si l'état est nok).
    $plugin_dir = realpath(dirname(__FILE__) . '/..');
    $venv = $plugin_dir . '/resources/venv/bin/python3';
    if (!file_exists($venv)) {
        try {
            $log = log::getPathToLog('hoymilescloud_update');
            exec('bash ' . escapeshellarg($plugin_dir . '/resources/install.sh') . ' >> ' . escapeshellarg($log) . ' 2>&1 &');
            log::add('hoymilescloud', 'info', 'Installation des dépendances lancée (venv Python)');
        } catch (Exception $e) {
            log::add('hoymilescloud', 'error', 'Erreur install: ' . $e->getMessage());
        }
    }
}

function hoymilescloud_remove()
{
    // Nettoyage : sans cela les crons continuent d'être appelés après
    // désinstallation (classe introuvable → erreurs dans le log cron).
    foreach (array('cron5', 'cron15') as $function) {
        $cron = cron::byClassAndFunction('hoymilescloud', $function);
        if (is_object($cron)) {
            $cron->remove();
        }
    }
    $tmp = jeedom::getTmpFolder('hoymilescloud');
    if (file_exists($tmp)) {
        exec('rm -rf ' . escapeshellarg($tmp));
    }
    log::add('hoymilescloud', 'info', 'Plugin désinstallé : crons supprimés, dossier temporaire purgé');
}
