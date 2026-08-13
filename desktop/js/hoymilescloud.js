/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 * La gestion des équipements/cartes/sauvegarde est assurée par plugin.template.js (core).
 * Ici : spécificités du plugin — aide + panneau d'état cloud rafraîchi en AJAX.
 */

// ---------- Panneau d'état cloud (rafraîchissement asynchrone) ----------
function refreshHoymilesStatus() {
    $.ajax({
        type: 'POST',
        url: 'plugins/hoymilescloud/core/ajax/hoymilescloud.ajax.php',
        data: { action: 'getStatus' },
        dataType: 'json',
        error: function () {
            $('#hoymilesStatusPanel').attr('class', 'alert alert-danger').html('<i class="fas fa-exclamation-triangle"></i> {{Impossible de joindre le serveur Jeedom}}');
        },
        success: function (data) {
            if (data.state != 'ok') {
                return;
            }
            var s = data.result;
            var d = s.daemon || {};
            var c = s.cloud || {};
            var st = s.station || null;
            var daemonState = d.state || 'nok';
            var cloudState = c.state || 'stopped';

            // Badge état du démon
            var badge, cls;
            if (daemonState == 'ok') {
                badge = '<span class="label label-success"><i class="fas fa-play"></i> Démon actif</span>';
            } else {
                badge = '<span class="label label-danger"><i class="fas fa-stop"></i> Démon arrêté</span>';
            }
            // Badge état cloud (santé de la liaison)
            var cloudBadge;
            if (daemonState != 'ok') {
                cloudBadge = '';
            } else if (cloudState == 'ok' && c.burst_ok && c.slow_ok) {
                cloudBadge = '<span class="label label-success"><i class="fas fa-cloud"></i> Cloud OK</span>';
            } else if (c.burst_ok === false && c.slow_ok === false && c.day_ok === false && daemonState == 'ok') {
                cloudBadge = '<span class="label label-warning"><i class="fas fa-cloud-sun"></i> Mode dégradé</span>';
            } else {
                cloudBadge = '<span class="label label-warning"><i class="fas fa-cloud-sun"></i> Liaison partielle</span>';
            }

            // Lignes de valeurs
            var lines = '';
            if (st) {
                var v = st.values || {};
                var fmt = function (val, unit) {
                    return (val === null || val === undefined || val === '') ? '—' : val + (unit ? ' ' + unit : '');
                };
                lines += '<div class="col-lg-3 col-md-6" style="padding:2px 8px;"><b>' + st.name + '</b></div>';
                lines += '<div class="col-lg-9 col-md-6" style="padding:2px 8px;">';
                lines += '<i class="fas fa-bolt"></i> {{Puissance}} <b>' + fmt(v.real_power, 'W') + '</b>';
                lines += ' &nbsp; <i class="fas fa-solar-panel"></i> {{Jour}} <b>' + fmt(v.today_eq, 'Wh') + '</b>';
                lines += ' &nbsp; <i class="fas fa-percent"></i> {{Auto}} <b>' + fmt(v.self_rate, '%') + '</b>';
                lines += '<br><i class="fas fa-clock"></i> {{Dernière donnée}} <b>' + fmt(v.last_data_time) + '</b>';
                lines += ' &nbsp; <i class="fas fa-heartbeat"></i> {{Démon}} <b>' + (v.daemon == '1' ? '<span class="label label-success">OK</span>' : '<span class="label label-danger">KO</span>') + '</b>';
                lines += '</div>';
            } else {
                lines = '<div class="col-lg-12">{{Aucun équipement synchronisé — cliquez sur « Configuration » puis « Synchroniser »}}</div>';
            }
            if (c.error) {
                lines += '<div class="col-lg-12" style="padding:2px 8px;"><span class="label label-warning"><i class="fas fa-exclamation-circle"></i> ' + c.error + '</span></div>';
            }

            $('#hoymilesStatusPanel')
                .attr('class', 'alert alert-' + (daemonState == 'ok' && cloudState == 'ok' ? 'success' : 'warning'))
                .html('<div class="row" style="margin:0;">' + badge + ' &nbsp; ' + cloudBadge + ' &nbsp; <small>{{équipements}} : ' + (s.eq_count || 0) + '</small>' + lines + '</div>');
            $('#hoymilesStatusAge').text('(' + s.now + ')');
        }
    });
}

// Bouton d'aide
$('#bt_helpHoymilesCloud').on('click', function () {
    bootbox.alert({
        title: 'Aide — Hoymiles Cloud',
        message: '<p>1. Configurez vos identifiants S-Miles dans <b>Plugins → Énergie → Hoymiles Cloud</b> (page de configuration).</p>' +
            '<p>2. Cliquez sur <b>Synchroniser les équipements</b> : la station et les micro-onduleurs sont créés automatiquement.</p>' +
            '<p>3. Démarrez le démon (état du plugin). Les valeurs sont poussées en temps réel (burst ~2-3 s) avec un seuil de changement configurable.</p>' +
            '<p>4. La commande <b>Démon OK</b> (station) est mise à jour toutes les 60 s — utilisez-la dans un scénario pour alerter si les données ne se rafraîchissent plus.</p>',
        buttons: { ok: { label: 'OK', className: 'btn-primary' } }
    });
});

// Rafraîchissement manuel + auto toutes les 15 s
$('#bt_refreshHoymilesStatus').on('click', function () {
    refreshHoymilesStatus();
});
setInterval(refreshHoymilesStatus, 15000);
refreshHoymilesStatus();

// Hook optionnel du template : affiche des infos cloud dans le panneau d'édition
window.printEqLogic = function (_eqLogic) {
    var type = _eqLogic.configuration ? _eqLogic.configuration.type : '';
    if (type) {
        var div = document.getElementById('div_cloudInfo');
        if (div) {
            div.textContent = 'Cloud : ' + (type == 'station' ? 'Station ' + (_eqLogic.configuration.sid || '') : 'Micro-onduleur');
        }
    }
};
