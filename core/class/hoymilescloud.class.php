<?php
/* This file is part of the Hoymiles Cloud plugin for Jeedom.
 * eqLogic + daemon lifecycle + cloud sync (S-Miles neapi API).
 */

class hoymilescloud extends eqLogic
{
    const PLUGIN_ID = 'hoymilescloud';
    const API_BASE = 'https://neapi.hoymiles.com';
    const API_EU_BASE = 'https://euapi.hoymiles.com';

    // Champs sensibles chiffrés en base
    public static $_encryptConfigKey = array('password');

    /* ===================== Lifecycle ===================== */

    public static function deamon_info()
    {
        $return = array();
        $return['log'] = log::getPathToLog('hoymilescloud_daemon');
        $return['state'] = 'nok';
        $pid_file = jeedom::getTmpFolder(self::PLUGIN_ID) . '/daemon.pid';
        if (file_exists($pid_file)) {
            $pid = trim(file_get_contents($pid_file));
            if (posix_getsid($pid) !== false) {
                $return['state'] = 'ok';
            } else {
                shell_exec('rm -f ' . escapeshellarg($pid_file));
            }
        }
        $return['launchable'] = 'ok';
        $user = config::byKey('user', self::PLUGIN_ID, '');
        if ($user == '') {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = 'Compte S-Miles non configuré (paramètres du plugin)';
        }
        return $return;
    }

    public static function deamon_start()
    {
        self::deamon_stop();
        $deamon_info = self::deamon_info();
        if ($deamon_info['launchable'] != 'ok') {
            throw new Exception(__('Vérifiez la configuration du plugin : ' . $deamon_info['launchable_message'], __FILE__));
        }
        self::generateConfig();

        $path = realpath(dirname(__FILE__) . '/../../resources');
        $cmd = 'nohup ' . $path . '/venv/bin/python3 ' . $path . '/hoymiles_daemon.py'
            . ' --config ' . jeedom::getTmpFolder(self::PLUGIN_ID) . '/config.json'
            . ' >> ' . log::getPathToLog('hoymilescloud_daemon') . ' 2>&1 &';
        exec($cmd);
        $i = 0;
        while ($i < 30) {
            $deamon_info = self::deamon_info();
            if ($deamon_info['state'] == 'ok') {
                break;
            }
            sleep(1);
            $i++;
        }
        if ($i >= 30) {
            log::add(self::PLUGIN_ID, 'error', 'Impossible de démarrer le démon, vérifiez le log hoymilescloud_daemon');
            return false;
        }
        message::add(self::PLUGIN_ID, 'Démon Hoymiles Cloud démarré');
        return true;
    }

    public static function deamon_stop()
    {
        $pid_file = jeedom::getTmpFolder(self::PLUGIN_ID) . '/daemon.pid';
        if (file_exists($pid_file)) {
            $pid = trim(file_get_contents($pid_file));
            if (posix_getsid($pid) !== false) {
                posix_kill($pid, 15);
            }
            shell_exec('rm -f ' . escapeshellarg($pid_file));
        }
        // kill de secours
        shell_exec('pkill -f hoymiles_daemon.py 2>/dev/null');
    }

    public static function deamon_changeAutoMode($mode)
    {
        self::deamon_stop();
    }

    /* ===================== Dépendances ===================== */

    public static function dependancy_info()
    {
        $return = array();
        $return['log'] = log::getPathToLog(self::PLUGIN_ID . '_dep');
        $return['progress_file'] = '/tmp/jeedom_install_in_progress_' . self::PLUGIN_ID;
        $venv = dirname(__FILE__) . '/../../resources/venv/bin/python3';
        $return['state'] = file_exists($venv) ? 'ok' : 'nok';
        return $return;
    }

    public static function dependancy_install()
    {
        $resource_path = realpath(dirname(__FILE__) . '/../../resources');
        return array(
            'script' => $resource_path . '/install.sh',
            'log' => log::getPathToLog(self::PLUGIN_ID . '_dep'),
        );
    }

    public static function cron15()
    {
        // Vérification périodique que le démon tourne
        if (config::byKey('user', self::PLUGIN_ID, '') == '') {
            return;
        }
        $deamon_info = self::deamon_info();
        if ($deamon_info['state'] != 'ok') {
            log::add(self::PLUGIN_ID, 'warning', 'Démon arrêté — redémarrage auto');
            self::deamon_start();
        }
    }

    /* ===================== Config runtime ===================== */

    public static function generateConfig()
    {
        // Mapping logicalId eqLogic → cmd_id par logicalId de commande
        $mapping = array();
        foreach (eqLogic::byType(self::PLUGIN_ID, true) as $eq) {
            $mapping[$eq->getLogicalId()] = array('eq_id' => $eq->getId(), 'cmds' => array());
            foreach ($eq->getCmd() as $cmd) {
                $mapping[$eq->getLogicalId()]['cmds'][$cmd->getLogicalId()] = $cmd->getId();
            }
        }

        $config = array(
            'user' => config::byKey('user', self::PLUGIN_ID, ''),
            'password' => config::byKey('password', self::PLUGIN_ID, '', true),
            'profile' => config::byKey('profile', self::PLUGIN_ID, 'auto'),
            'burst_interval' => intval(config::byKey('burst_interval', self::PLUGIN_ID, 2)),
            'delta_threshold' => floatval(config::byKey('delta_threshold', self::PLUGIN_ID, 1)),
            'slow_interval' => intval(config::byKey('slow_interval', self::PLUGIN_ID, 60)),
            'jeedom_url' => 'http://127.0.0.1',
            'apikey' => jeedom::getApiKey(self::PLUGIN_ID),
            'log' => log::getPathToLog('hoymilescloud_daemon'),
            'mapping' => $mapping,
        );
        $dir = jeedom::getTmpFolder(self::PLUGIN_ID);
        if (!file_exists($dir)) {
            mkdir($dir, 0775, true);
        }
        file_put_contents($dir . '/config.json', json_encode($config));
        log::add(self::PLUGIN_ID, 'debug', 'Config runtime générée (' . count($mapping) . ' équipement(s) mappé(s))');
    }

    /* ===================== Sync cloud (AJAX) ===================== */

    public static function testConnection()
    {
        $user = config::byKey('user', self::PLUGIN_ID, '');
        $pass = config::byKey('password', self::PLUGIN_ID, '', true);
        if ($user == '' || $pass == '') {
            return array('ok' => false, 'message' => 'Identifiants manquants');
        }
        $api = new HoymilesCloudApi($user, $pass);
        $result = $api->login();
        if (!$result['ok']) {
            return array('ok' => false, 'message' => 'Login échoué : ' . $result['message']);
        }
        $stations = $api->getStations();
        $msg = 'Connecté (' . $result['method'] . '). ' . count($stations) . ' station(s) trouvée(s)';
        if (count($stations) > 0) {
            $first = reset($stations);
            $msg .= ' : "' . $first['name'] . '" (id ' . $first['id'] . ')';
        }
        return array('ok' => true, 'message' => $msg, 'stations' => $stations);
    }

    public static function syncFromCloud()
    {
        $user = config::byKey('user', self::PLUGIN_ID, '');
        $pass = config::byKey('password', self::PLUGIN_ID, '', true);
        if ($user == '' || $pass == '') {
            throw new Exception(__('Identifiants S-Miles manquants dans la configuration', __FILE__));
        }
        $api = new HoymilesCloudApi($user, $pass);
        $login = $api->login();
        if (!$login['ok']) {
            throw new Exception(__('Login S-Miles échoué : ', __FILE__) . $login['message']);
        }

        $stations = $api->getStations();
        if (count($stations) == 0) {
            throw new Exception(__('Aucune station trouvée sur ce compte', __FILE__));
        }

        $created = 0;
        foreach ($stations as $station) {
            $sid = $station['id'];
            $eqStation = self::getOrCreateEqLogic('station-' . $sid, $station['name'], 'Station');
            self::createStationCommands($eqStation, $sid);
            $created++;

            $micros = $api->getMicros($sid);
            foreach ($micros as $micro) {
                $sn = $micro['sn'];
                $model = isset($micro['model_no']) && $micro['model_no'] != '' ? $micro['model_no'] : 'HMS';
                $eqMicro = self::getOrCreateEqLogic('micro-' . $sn, $model . ' (' . $sn . ')', 'Micro-onduleur');
                self::createMicroCommands($eqMicro);
                $eqMicro->setConfiguration('sn', $sn);
                $eqMicro->setConfiguration('sid', $sid);
                $eqMicro->save();
                $created++;
            }
        }
        return array('ok' => true, 'message' => $created . ' équipement(s) synchronisé(s)');
    }

    private static function getOrCreateEqLogic($logicalId, $name, $type)
    {
        $eq = self::byLogicalId($logicalId, self::PLUGIN_ID);
        $isNew = false;
        if (!is_object($eq)) {
            $eq = new self();
            $eq->setEqType_name(self::PLUGIN_ID);
            $eq->setLogicalId($logicalId);
            $eq->setIsEnable(1);
            $eq->setIsVisible(1);
            $isNew = true;
        }
        // Le nom n'est appliqué qu'à la création : un équipement renommé par
        // l'utilisateur n'est jamais re-renommé par la synchronisation.
        if ($isNew) {
            $eq->setName($name);
        }
        $eq->setConfiguration('type', $type);
        $eq->setConfiguration('autorefresh', '');
        $eq->save();
        return $eq;
    }

    private static function createCommand($eqLogic, $logicalId, $name, $type, $subtype, $unite = '', $template = '')
    {
        $cmd = $eqLogic->getCmd(null, $logicalId);
        $isNew = false;
        if (!is_object($cmd)) {
            $cmd = new hoymilescloudCmd();
            $cmd->setEqLogic_id($eqLogic->getId());
            $cmd->setLogicalId($logicalId);
            $cmd->setIsVisible(1);
            $isNew = true;
        }
        // Nom uniquement à la création : préserve les noms personnalisés.
        if ($isNew) {
            $cmd->setName($name);
        }
        $cmd->setType($type);
        $cmd->setSubType($subtype);
        $cmd->setUnite($unite);
        if ($template != '') {
            $cmd->setTemplate('dashboard', $template);
            $cmd->setTemplate('mobile', $template);
        }
        $cmd->setConfiguration('history', $type == 'info' && $subtype == 'numeric' ? 1 : 0);
        $cmd->save();
        return $cmd;
    }

    private static function createStationCommands($eq, $sid)
    {
        $eq->setConfiguration('sid', $sid);
        $eq->save();
        self::createCommand($eq, 'real_power', 'Puissance PV', 'info', 'numeric', 'W', 'power');
        self::createCommand($eq, 'today_eq', 'Production jour', 'info', 'numeric', 'Wh');
        self::createCommand($eq, 'month_eq', 'Production mois', 'info', 'numeric', 'Wh');
        self::createCommand($eq, 'total_eq', 'Production totale', 'info', 'numeric', 'Wh');
        self::createCommand($eq, 'self_rate', 'Autoconsommation', 'info', 'numeric', '%');
        self::createCommand($eq, 'co2', 'CO2 évité', 'info', 'numeric', 'g');
        self::createCommand($eq, 'last_data_time', 'Dernière donnée', 'info', 'string');
        self::createCommand($eq, 'online', 'Connecté', 'info', 'binary', '', 'state');
    }

    private static function createMicroCommands($eq)
    {
        self::createCommand($eq, 'pac', 'Puissance AC', 'info', 'numeric', 'W', 'power');
        self::createCommand($eq, 'p1', 'PV1', 'info', 'numeric', 'W');
        self::createCommand($eq, 'p2', 'PV2', 'info', 'numeric', 'W');
        self::createCommand($eq, 'p3', 'PV3', 'info', 'numeric', 'W');
        self::createCommand($eq, 'p4', 'PV4', 'info', 'numeric', 'W');
        self::createCommand($eq, 'connect', 'Connecté', 'info', 'binary', '', 'state');
        self::createCommand($eq, 'soft_ver', 'Firmware', 'info', 'string');
    }
}

class hoymilescloudCmd extends cmd
{
}

/* ===================== Client API (PHP, pour la synchro) ===================== */

class HoymilesCloudApi
{
    private $user;
    private $pass;
    private $token = null;

    const PROFILES = array(
        'home' => array('base' => 'https://euapi.hoymiles.com', 'ua' => 'sma/ad/2.10.0/159/0'),
        'installer' => array('base' => 'https://neapi.hoymiles.com', 'ua' => 'S-Miles Installer/3.7.1', 'xct' => 'mobile'),
        'web' => array('base' => 'https://neapi.hoymiles.com', 'ua' => 'HomeAssistant-HoymilesCloud'),
    );

    public function __construct($user, $pass)
    {
        $this->user = $user;
        $this->pass = $pass;
    }

    private function post($url, $payload, $profile = 'home', $token = null)
    {
        $headers = array(
            'Content-Type: application/json',
            'User-Agent: ' . self::PROFILES[$profile]['ua'],
        );
        if (isset(self::PROFILES[$profile]['xct'])) {
            $headers[] = 'X-Client-Type: ' . self::PROFILES[$profile]['xct'];
        }
        if ($token !== null) {
            $headers[] = 'Authorization: ' . $token;
        }
        $ch = curl_init($url);
        curl_setopt_array($ch, array(
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => json_encode($payload),
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 20,
            CURLOPT_SSL_VERIFYPEER => true,
        ));
        $body = curl_exec($ch);
        curl_close($ch);
        $json = json_decode($body, true);
        return is_array($json) ? $json : array('status' => 'x', 'message' => 'Réponse non JSON');
    }

    private function argon2id($salt)
    {
        // salt: hex ou base64 → 16 octets
        $raw = trim($salt);
        if (strlen($raw) == 32 && ctype_xdigit($raw)) {
            $sb = hex2bin($raw);
        } else {
            $sb = base64_decode($raw, true);
            if ($sb === false) {
                $sb = $raw;
            }
        }
        $hash = sodium_crypto_pwhash(32, $this->pass, $sb, 3, 32768 * 1024, SODIUM_CRYPTO_PWHASH_ALG_ARGON2ID13);
        return bin2hex($hash);
    }

    public function login()
    {
        // 1) v3 home (euapi + UA sma/ad) — profil confirmé pour les comptes S-Miles Home
        $profiles = array('home', 'installer', 'web');
        foreach ($profiles as $profile) {
            $base = self::PROFILES[$profile]['base'];
            $pre = $this->post($base . '/iam/pub/3/auth/pre-insp', array('u' => $this->user), $profile);
            if (!isset($pre['data']) || !is_array($pre['data'])) {
                continue;
            }
            $data = $pre['data'];
            if (!isset($data['n']) || $data['n'] == '') {
                continue;
            }
            $salt = isset($data['a']) ? $data['a'] : null;
            if ($salt !== null && $salt !== '') {
                try {
                    $ch = $this->argon2id($salt);
                } catch (Exception $e) {
                    continue;
                }
                $resp = $this->post($base . '/iam/pub/3/auth/login', array('u' => $this->user, 'ch' => $ch, 'n' => $data['n']), $profile);
                if ($resp['status'] === '0' && isset($resp['data']['token'])) {
                    $this->token = $resp['data']['token'];
                    return array('ok' => true, 'method' => 'v3/' . $profile);
                }
            }
        }
        // 2) fallback v0 (md5)
        $md5 = md5($this->pass);
        $resp = $this->post(hoymilescloud::API_BASE . '/iam/pub/0/auth/login', array('user_name' => $this->user, 'password' => $md5), 'web');
        if ($resp['status'] === '0' && isset($resp['data']['token'])) {
            $this->token = $resp['data']['token'];
            return array('ok' => true, 'method' => 'v0');
        }
        return array('ok' => false, 'message' => isset($resp['message']) ? $resp['message'] : 'inconnu');
    }

    public function getStations()
    {
        $resp = $this->post(hoymilescloud::API_BASE . '/pvm/api/0/station/select_by_page', array('page_size' => 100, 'page_num' => 1), 'home', $this->token);
        $list = isset($resp['data']['list']) ? $resp['data']['list'] : array();
        $out = array();
        foreach ($list as $s) {
            $out[] = array('id' => $s['id'], 'name' => isset($s['name']) ? $s['name'] : ('Station ' . $s['id']));
        }
        return $out;
    }

    public function getMicros($sid)
    {
        $resp = $this->post(hoymilescloud::API_BASE . '/pvm/api/0/dev/micro/select_by_station', array('sid' => $sid, 'page_size' => 1000, 'page_num' => 1, 'show_warn' => 0), 'home', $this->token);
        $list = isset($resp['data']['list']) ? $resp['data']['list'] : array();
        $out = array();
        foreach ($list as $m) {
            $out[] = array('sn' => $m['sn'], 'model_no' => isset($m['model_no']) ? $m['model_no'] : '');
        }
        return $out;
    }
}
