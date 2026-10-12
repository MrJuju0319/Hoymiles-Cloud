<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 * Configuration page — credentials S-Miles + polling options + maintenance.
 * Libellés entre {{ }} : traduisibles (core/i18n/en_US.json).
 */
?>

<fieldset>
    <legend><i class="fas fa-user"></i> {{Compte S-Miles}}</legend>
    <div class="form-group">
        <label class="col-sm-3 control-label">{{Compte S-Miles (email)}}</label>
        <div class="col-sm-3">
            <input class="configKey form-control" data-l1key="user" placeholder="{{ex: julien@exemple.fr}}" />
        </div>
        <label class="col-sm-3 control-label">{{Mot de passe}}</label>
        <div class="col-sm-3">
            <input type="password" class="configKey form-control" data-l1key="password" placeholder="********" />
            <span class="help-block">{{Le mot de passe est chiffré en base par Jeedom et n'est jamais écrit en clair dans les fichiers du plugin.}}</span>
        </div>
    </div>
    <div class="form-group">
        <label class="col-sm-3 control-label">{{Type de compte}}</label>
        <div class="col-sm-3">
            <select class="configKey form-control" data-l1key="profile">
                <option value="auto">{{Auto (recommandé)}}</option>
                <option value="home">{{S-Miles Home (app balcon)}}</option>
                <option value="installer">{{S-Miles Installer / Cloud Web}}</option>
            </select>
        </div>
        <div class="col-sm-6">
            <a class="btn btn-info" id="bt_testHoymilesCloud"><i class="fas fa-plug"></i> {{Tester la connexion}}</a>
            <a class="btn btn-success" id="bt_syncHoymilesCloud"><i class="fas fa-sync"></i> {{Synchroniser les équipements}}</a>
            <span id="hoymilesSyncResult" style="margin-left:10px;"></span>
        </div>
    </div>
</fieldset>

<fieldset>
    <legend><i class="fas fa-tachometer-alt"></i> {{Rafraîchissement}}</legend>
    <div class="form-group">
        <label class="col-sm-3 control-label">{{Intervalle minimum burst (s)}}</label>
        <div class="col-sm-3">
            <input class="configKey form-control" data-l1key="burst_interval" placeholder="2" />
            <span class="help-block">{{Plancher entre deux mesures temps réel : le serveur S-Miles impose lui-même son rythme (1,5 à 3 s).}}</span>
        </div>
        <label class="col-sm-3 control-label">{{Seuil de changement (W)}}</label>
        <div class="col-sm-3">
            <input class="configKey form-control" data-l1key="delta_threshold" placeholder="1" />
            <span class="help-block">{{Valeur minimale de changement pour pousser vers Jeedom (évite le flood d'historique).}}</span>
        </div>
    </div>
    <div class="form-group">
        <label class="col-sm-3 control-label">{{Polling énergies (s)}}</label>
        <div class="col-sm-3">
            <input class="configKey form-control" data-l1key="slow_interval" placeholder="60" />
            <span class="help-block">{{Énergies, statut et heartbeat du démon.}}</span>
        </div>
        <label class="col-sm-3 control-label">{{Données électriques (s)}}</label>
        <div class="col-sm-3">
            <input class="configKey form-control" data-l1key="day_data_interval" placeholder="300" />
            <span class="help-block">{{Tensions, courants, fréquence, température (minimum 300 s).}}</span>
        </div>
    </div>
    <div class="form-group">
        <label class="col-sm-3 control-label">{{Niveau de log du démon}}</label>
        <div class="col-sm-3">
            <select class="configKey form-control" data-l1key="log_level">
                <option value="info">{{Normal}}</option>
                <option value="debug">{{Détaillé (diagnostic)}}</option>
                <option value="warning">{{Réduit (erreurs seulement)}}</option>
            </select>
        </div>
        <label class="col-sm-3 control-label">{{Rapport quotidien}}</label>
        <div class="col-sm-3">
            <select class="configKey form-control" data-l1key="daily_report">
                <option value="1">{{Oui (21 h, message Jeedom)}}</option>
                <option value="0">{{Non}}</option>
            </select>
            <span class="help-block">{{Production du jour, comparaison veille, pic et détail par micro.}}</span>
        </div>
    </div>
</fieldset>

<fieldset>
    <legend><i class="fas fa-tools"></i> {{Maintenance}}</legend>
    <div class="form-group">
        <label class="col-sm-3 control-label">{{Historique}}</label>
        <div class="col-sm-9">
            <a class="btn btn-primary" id="bt_repairHistory"><i class="fas fa-chart-line"></i> {{Réparer l'historisation}}</a>
            <a class="btn btn-primary" id="bt_runBackfill"><i class="fas fa-history"></i> {{Récupérer l'historique (15 jours)}}</a>
            <span id="hoymilesMaintenanceResult" style="margin-left:10px;"></span>
            <span class="help-block">{{« Réparer l'historisation » coche la case Historiser des commandes numériques (utile si les courbes sont vides). « Récupérer l'historique » importe les 15 derniers jours de mesures depuis le cloud — l'opération dure environ une minute.}}</span>
        </div>
    </div>
</fieldset>

<script>
    // JS inline obligatoire sur la page de configuration (les fichiers externes n'y sont pas chargés)
    function hoymilesAjax(action, $target, data) {
        $target.empty();
        var payload = { action: action };
        if (data) {
            $.extend(payload, data);
        }
        $.ajax({
            type: 'POST',
            url: 'plugins/hoymilescloud/core/ajax/hoymilescloud.ajax.php',
            data: payload,
            dataType: 'json',
            error: function () { $target.showAlert({ message: '{{Erreur réseau}}', level: 'danger' }); },
            success: function (data) {
                if (data.state != 'ok') {
                    $target.showAlert({ message: data.result, level: 'danger' });
                    return;
                }
                var message = (typeof data.result === 'object' && data.result !== null) ? data.result.message : data.result;
                $target.showAlert({ message: message, level: 'success' });
            }
        });
    }

    $('#bt_syncHoymilesCloud').on('click', function () {
        hoymilesAjax('syncFromCloud', $('#hoymilesSyncResult'));
    });
    $('#bt_testHoymilesCloud').on('click', function () {
        hoymilesAjax('testConnection', $('#hoymilesSyncResult'));
    });
    $('#bt_repairHistory').on('click', function () {
        hoymilesAjax('repairHistory', $('#hoymilesMaintenanceResult'));
    });
    $('#bt_runBackfill').on('click', function () {
        hoymilesAjax('runBackfill', $('#hoymilesMaintenanceResult'));
    });
</script>
