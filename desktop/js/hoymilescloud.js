/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 * La gestion des équipements/cartes/sauvegarde est assurée par plugin.template.js (core).
 * Ici : uniquement les spécificités du plugin.
 */

// Bouton d'aide
$('#bt_helpHoymilesCloud').on('click', function () {
    bootbox.alert({
        title: 'Aide — Hoymiles Cloud',
        message: '<p>1. Configurez vos identifiants S-Miles dans <b>Plugins → Énergie → Hoymiles Cloud</b> (page de configuration).</p>' +
            '<p>2. Cliquez sur <b>Synchroniser les équipements</b> : la station et les micro-onduleurs sont créés automatiquement.</p>' +
            '<p>3. Démarrez le démon (état du plugin). Les valeurs sont poussées en temps réel (burst ~2-3 s) avec un seuil de changement configurable.</p>',
        buttons: { ok: { label: 'OK', className: 'btn-primary' } }
    });
});

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
