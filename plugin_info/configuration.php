<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 * Configuration page — credentials S-Miles + polling options.
 */
?>

<div class="form-group">
    <label class="col-sm-3 control-label">Compte S-Miles (email)</label>
    <div class="col-sm-3">
        <input class="configKey form-control" data-l1key="user" placeholder="ex: julien@exemple.fr" />
    </div>
    <label class="col-sm-3 control-label">Mot de passe</label>
    <div class="col-sm-3">
        <input type="password" class="configKey form-control" data-l1key="password" placeholder="********" />
    </div>
</div>

<div class="form-group">
    <label class="col-sm-3 control-label">Type de compte</label>
    <div class="col-sm-3">
        <select class="configKey form-control" data-l1key="profile">
            <option value="auto">Auto (recommandé)</option>
            <option value="home">S-Miles Home (app balcon)</option>
            <option value="installer">S-Miles Installer / Cloud Web</option>
        </select>
    </div>
    <label class="col-sm-3 control-label">Intervalle burst (s)</label>
    <div class="col-sm-3">
        <input class="configKey form-control" data-l1key="burst_interval" placeholder="2 (rythme serveur ~1,5-3 s)" />
    </div>
</div>

<div class="form-group">
    <label class="col-sm-3 control-label">Seuil de changement (W)</label>
    <div class="col-sm-3">
        <input class="configKey form-control" data-l1key="delta_threshold" placeholder="1" />
        <span class="help-block">Valeur minimale de changement pour pousser vers Jeedom (évite le flood d'historique).</span>
    </div>
    <label class="col-sm-3 control-label">Polling énergies (s)</label>
    <div class="col-sm-3">
        <input class="configKey form-control" data-l1key="slow_interval" placeholder="60" />
    </div>
</div>

<div class="form-group">
    <label class="col-sm-3 control-label">Synchroniser le cloud</label>
    <div class="col-sm-9">
        <a class="btn btn-success" id="bt_syncHoymilesCloud"><i class="fas fa-sync"></i> Synchroniser les équipements</a>
        <a class="btn btn-info" id="bt_testHoymilesCloud"><i class="fas fa-plug"></i> Tester la connexion</a>
        <span id="hoymilesSyncResult" style="margin-left:10px;"></span>
    </div>
</div>

<script>
    // JS inline obligatoire sur la page de configuration (les fichiers externes n'y sont pas chargés)
    $('#bt_syncHoymilesCloud').on('click', function () {
        $('#hoymilesSyncResult').empty();
        $.ajax({
            type: 'POST',
            url: 'plugins/hoymilescloud/core/ajax/hoymilescloud.ajax.php',
            data: { action: 'syncFromCloud' },
            dataType: 'json',
            error: function () { $('#hoymilesSyncResult').showAlert({ message: 'Erreur réseau', level: 'danger' }); },
            success: function (data) {
                if (data.state != 'ok') {
                    $('#hoymilesSyncResult').showAlert({ message: data.result, level: 'danger' });
                    return;
                }
                $('#hoymilesSyncResult').showAlert({ message: data.result.message, level: 'success' });
            }
        });
    });
    $('#bt_testHoymilesCloud').on('click', function () {
        $('#hoymilesSyncResult').empty();
        $.ajax({
            type: 'POST',
            url: 'plugins/hoymilescloud/core/ajax/hoymilescloud.ajax.php',
            data: { action: 'testConnection' },
            dataType: 'json',
            error: function () { $('#hoymilesSyncResult').showAlert({ message: 'Erreur réseau', level: 'danger' }); },
            success: function (data) {
                if (data.state != 'ok') {
                    $('#hoymilesSyncResult').showAlert({ message: data.result, level: 'danger' });
                    return;
                }
                $('#hoymilesSyncResult').showAlert({ message: data.result.message, level: 'success' });
            }
        });
    });
</script>
