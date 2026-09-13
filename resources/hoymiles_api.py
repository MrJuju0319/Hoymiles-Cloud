#!/usr/bin/env python3
"""HoymilesCloudApi — client API S-Miles (neapi/euapi), profil S-Miles Home.

Confirmé en live le 13/08/2026 sur un compte S-Miles Home (Argon2id v3,
User-Agent sma/ad/2.10.0/159/0 obligatoire, auth sur euapi.hoymiles.com).
"""
import base64
import hashlib
import hmac
import os
import subprocess
import threading
import time

import requests

API_BASE = "https://neapi.hoymiles.com"
EU_BASE = "https://euapi.hoymiles.com"

PROFILES = {
    "home": {"base": EU_BASE, "ua": "sma/ad/2.10.0/159/0"},
    "installer": {"base": API_BASE, "ua": "S-Miles Installer/3.7.1", "xct": "mobile"},
    "web": {"base": API_BASE, "ua": "HomeAssistant-HoymilesCloud"},
}

TOKEN_TTL = 7200  # validité observée ~2h
URI_REFRESH_MS = 240000  # le token k de l'URI burst expire
HTTP_TIMEOUT = 10  # timeout strict : un blocage réseau ne doit jamais figer le démon

# Codes d'alarme des micro-onduleurs Hoymiles (enum AlarmReason du protocole DTU,
# identique côté OpenDTU) → libellés français lisibles pour Jeedom.
ALARM_MESSAGES = {
    1: "Autre anomalie",
    2: "Surtension DC (panneau)",
    3: "Sous-tension DC (panneau)",
    4: "Surtension réseau (grid over voltage)",
    5: "Sous-tension réseau (grid under voltage)",
    6: "Sur-température (over-temperature)",
    7: "Sur-courant DC (panneau)",
    8: "Sous-courant DC (panneau)",
    9: "Sur-courant AC (réseau)",
    10: "Sous-courant AC (réseau)",
    11: "Défaut d'isolement",
    12: "Défaut de courant résiduel",
    13: "Injection DC",
    14: "Défaut relais",
    15: "Fréquence réseau trop élevée",
    16: "Fréquence réseau trop basse",
}


def jeedom_decrypt(value, jeedom_root):
    """Déchiffre une valeur `crypt:...` produite par utils::encrypt() du core Jeedom
    (AES-256-CBC + HMAC, clé dans data/jeedom_encryption.key).
    Retourne la valeur en clair ; si le format n'est pas reconnu, retourne telle quelle
    (rétrocompatibilité avec les anciennes configs runtime en clair)."""
    if not value or not str(value).startswith("crypt:"):
        return value
    key_path = os.path.join(jeedom_root, "data", "jeedom_encryption.key")
    try:
        with open(key_path, "rb") as f:
            enc_password = f.read().strip()
        raw = base64.b64decode(str(value)[6:])
        iv, mac, ciphertext = raw[:16], raw[16:48], raw[48:]
        aes_key = hashlib.sha256(enc_password).digest()
        if not hmac.compare_digest(
            hmac.new(aes_key, ciphertext + iv, hashlib.sha256).digest(), mac):
            raise ValueError("HMAC mismatch")
        proc = subprocess.run(
            ["openssl", "enc", "-d", "-aes-256-cbc", "-K", aes_key.hex(), "-iv", iv.hex()],
            input=ciphertext, capture_output=True, timeout=5)
        if proc.returncode != 0:
            raise ValueError("openssl décodage échoué")
        return proc.stdout.decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Impossible de déchiffrer le mot de passe (clé {key_path}) : {e}")


class HoymilesCloudApi:
    def __init__(self, user, password, profile="auto", timeout=HTTP_TIMEOUT):
        self.user = user
        self.password = password
        self.timeout = timeout
        self.token = None
        self.token_at = 0
        self.method = None
        self.profile_pref = profile
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        self._auth_lock = threading.Lock()

    # ---------- HTTP ----------
    def _post(self, url, payload, profile="home", token=None):
        h = {"Content-Type": "application/json", "User-Agent": PROFILES[profile]["ua"]}
        if PROFILES[profile].get("xct"):
            h["X-Client-Type"] = PROFILES[profile]["xct"]
        if token:
            h["Authorization"] = token
        r = self.session.post(url, json=payload, headers=h, timeout=self.timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"status": "x", "message": "non-JSON", "raw": r.text[:200]}

    # ---------- Auth ----------
    @staticmethod
    def _argon2id_ch(password, salt):
        from argon2.low_level import hash_secret_raw, Type
        raw = salt.strip()
        try:
            sb = bytes.fromhex(raw) if len(raw) % 2 == 0 and len(raw) == 32 else None
        except ValueError:
            sb = None
        if sb is None:
            sb = base64.b64decode(raw, validate=True) if raw else raw.encode()
        digest = hash_secret_raw(secret=password.encode(), salt=sb, time_cost=3,
                                 memory_cost=32768, parallelism=1, hash_len=32, type=Type.ID)
        return digest.hex()

    def login(self):
        candidates = ["home", "installer", "web"]
        if self.profile_pref in PROFILES:
            candidates = [self.profile_pref]

        for profile in candidates:
            base = PROFILES[profile]["base"]
            code, pre = self._post(f"{base}/iam/pub/3/auth/pre-insp", {"u": self.user}, profile)
            data = (pre.get("data") or {}) if isinstance(pre.get("data"), dict) else {}
            nonce = data.get("n")
            if not nonce:
                continue
            salt = data.get("a")
            if not salt:
                continue
            try:
                ch = self._argon2id_ch(self.password, salt)
            except Exception:
                continue
            code, resp = self._post(f"{base}/iam/pub/3/auth/login",
                                    {"u": self.user, "ch": ch, "n": nonce}, profile)
            if resp.get("status") == "0" and resp.get("data", {}).get("token"):
                self.token = resp["data"]["token"]
                self.token_at = time.time()
                self.method = f"v3/{profile}"
                return True
        # fallback v0 (md5) — rarement utile pour les comptes Home mais gratuit
        md5pw = hashlib.md5(self.password.encode()).hexdigest()
        code, resp = self._post(f"{API_BASE}/iam/pub/0/auth/login",
                                {"user_name": self.user, "password": md5pw}, "web")
        if resp.get("status") == "0" and resp.get("data", {}).get("token"):
            self.token = resp["data"]["token"]
            self.token_at = time.time()
            self.method = "v0"
            return True
        return False

    def ensure_token(self, force=False):
        # Verrouillé : plusieurs threads (burst/slow/day_data) peuvent demander
        # un token simultanément — un double login déclencherait le cooldown.
        with self._auth_lock:
            if force or not self.token or (time.time() - self.token_at) > TOKEN_TTL - 300:
                if not self.login():
                    raise RuntimeError("Login S-Miles échoué")

    def _auth_post(self, path, payload):
        self.ensure_token()
        code, resp = self._post(API_BASE + path, payload, "home", self.token)
        if resp.get("status") == "100":
            self.ensure_token(force=True)
            code, resp = self._post(API_BASE + path, payload, "home", self.token)
        return resp

    # ---------- Données ----------
    def get_stations(self):
        resp = self._auth_post("/pvm/api/0/station/select_by_page", {"page_size": 100, "page_num": 1})
        return resp.get("data", {}).get("list", [])

    def get_micros(self, sid):
        resp = self._auth_post("/pvm/api/0/dev/micro/select_by_station",
                               {"sid": sid, "page_size": 1000, "page_num": 1, "show_warn": 0})
        return resp.get("data", {}).get("list", [])

    def get_micro_alarms(self, sid):
        """État d'alarme de chaque micro — normalisé {sn: {"warn": bool, "connect": bool}}.

        IMPORTANT : `show_warn=1` est OBLIGATOIRE — avec show_warn=0, warn_data
        revient vide {} (connect=false à tort). Les codes détaillés arrivent par
        le protobuf down_module_day_data (champs int16 par bucket → alarm_codes)."""
        resp = self._auth_post("/pvm/api/0/dev/micro/select_by_station",
                               {"sid": sid, "page_size": 1000, "page_num": 1, "show_warn": 1})
        alarms = {}
        for m in resp.get("data", {}).get("list", []):
            sn = m.get("sn")
            if not sn:
                continue
            wd = m.get("warn_data") or {}
            alarms[sn] = {
                "warn": bool(wd.get("warn")),
                "connect": bool(wd.get("connect")),
            }
        return alarms

    def get_realtime(self, sid):
        """count_station_real_data — énergies + puissance instantanée."""
        resp = self._auth_post("/pvm-data/api/0/station/data/count_station_real_data", {"sid": sid})
        return resp.get("data", {})

    def get_burst_uri(self, sid):
        resp = self._auth_post("/pvm/api/0/station/get_sd_uri", {"sid": sid})
        return resp.get("data", {}).get("uri")

    def burst(self, uri, mode=0, mis=None):
        """POST sur l'URI burst. mode 0 = station, mode 3 = micros.
        Nécessite le header Authorization (sinon 400).
        Token expiré (status 100) → re-login + 1 retry."""
        body = {"m": mode, "t": 1}
        if mis:
            body["mis"] = mis
        h = {"Content-Type": "application/json", "User-Agent": PROFILES["home"]["ua"],
             "Authorization": self.token}
        for attempt in range(2):
            r = self.session.post(uri, json=body, headers=h, timeout=self.timeout)
            try:
                resp = r.json()
            except Exception:
                return r.status_code, {"status": "x", "message": "non-JSON"}
            if resp.get("status") == "100":
                self.ensure_token(force=True)
                h["Authorization"] = self.token
                continue
            return r.status_code, resp
        return r.status_code, resp

    # ---------- Données jour (protobuf) : tension/courant/température ----------
    def get_day_data(self, sid, date):
        """down_module_day_data — toutes les données du jour (buckets 5 min) en protobuf.
        Contient par micro : uac (tension réseau), freq, temp (température interne)
        et par port : tension DC, courant DC, puissance DC.
        Retourne les bytes bruts, ou None."""
        h = {"Content-Type": "application/json", "User-Agent": PROFILES["home"]["ua"],
             "Authorization": self.token}
        url = API_BASE + "/pvm-data/api/0/module/data/down_module_day_data"
        for attempt in range(2):
            r = self.session.post(url, json={"sid": sid, "date": date}, headers=h, timeout=15)
            if r.status_code == 200 and r.content and r.content[:1] != b"{":
                return r.content
            # token expiré → refresh + 1 retry
            try:
                j = r.json()
            except Exception:
                return None
            if j.get("status") == "100":
                self.ensure_token()
                h["Authorization"] = self.token
                continue
            return None
        return None


def _pb_varint(data, pos):
    shift = 0
    result = 0
    while True:
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            return result, pos
        shift += 7


def _pb_parse(data, end=None):
    """Parseur protobuf minimal → liste de (field, wire, value).
    wire 0 = varint, 2 = bytes, 5 = fixed32 (int brut), 1 = fixed64."""
    fields = []
    pos = 0
    end = len(data) if end is None else end
    while pos < end:
        tag, pos = _pb_varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            v, pos = _pb_varint(data, pos)
            fields.append((field, wire, v))
        elif wire == 2:
            ln, pos = _pb_varint(data, pos)
            fields.append((field, wire, data[pos:pos + ln]))
            pos += ln
        elif wire == 5:
            import struct as _s
            fields.append((field, wire, _s.unpack("<I", data[pos:pos + 4])[0]))
            pos += 4
        elif wire == 1:
            import struct as _s
            fields.append((field, wire, _s.unpack("<Q", data[pos:pos + 8])[0]))
            pos += 8
        else:
            raise ValueError(f"wire type {wire}")
    return fields


def _pb_f32(v):
    import struct as _s
    return _s.unpack("<f", _s.pack("<I", v))[0]


def parse_day_data(blob):
    """Parse le protobuf down_module_day_data → dict :
    {'sid': int, 'date': str, 'micros': {micro_id: {'times': [...],
      'uac': float, 'freq': float, 'temp': float,
      'ports': {port: {'up': float, 'ip': float, 'p': float}}}}}"""
    import struct as _s
    result = {"sid": None, "date": None, "micros": {}}
    for f, w, v in _pb_parse(blob):
        if f == 1 and w == 0:
            result["sid"] = v
        elif f == 2 and w == 2:
            result["date"] = v.decode(errors="ignore")
        elif f == 3 and w == 2:
            micro = {}
            for mf, mw, mv in _pb_parse(v):
                if mf == 1 and mw == 0:
                    micro["id"] = mv
                elif mf == 2 and mw == 2:
                    micro["main"] = mv
            mid = micro.get("id")
            if mid is None:
                continue
            times = []
            ports = {}
            ac_series = {}
            alarm_codes = []
            for mf, mw, mv in _pb_parse(micro.get("main") or b""):
                if mf == 2 and mw == 2:
                    s = mv.decode(errors="ignore")
                    if ":" in s and "-" not in s and len(s) == 5:
                        times.append(s)
                elif mf == 4 and mw == 2:
                    # port msg : field 1 varint = port, field 2 = batch de points
                    # (batch : field 1 repeated = points ; point : fixed32 1=up 2=ip 3=watt)
                    port = None
                    pts = []
                    for pf, pw, pv in _pb_parse(mv):
                        if pf == 1 and pw == 0:
                            port = pv
                        elif pf == 2 and pw == 2:
                            for qf, qw, qv in _pb_parse(pv):
                                if qf == 1 and qw == 2:
                                    vals = []
                                    for rf, rw, rv in _pb_parse(qv):
                                        # 1=up 2=ip 3=watt 4=énergie cumulée jour (Wh)
                                        if rf in (1, 2, 3, 4) and rw == 5:
                                            vals.append(_pb_f32(rv))
                                    if vals:
                                        pts.append(vals)
                    if port is not None and pts:
                        ports[port] = pts
                elif mf in (5, 6, 7) and mw == 2:
                    n = len(mv) // 4
                    ac_series[mf] = list(_s.unpack(f"<{n}f", mv))
                elif mf in (8, 9) and mw == 2:
                    # Champs int16 par bucket : codes d'alarme (0 = pas d'alarme).
                    # Décodés et agrégés en liste de codes non nuls (sans doublons,
                    # ordre d'apparition) — consommés par le daemon pour le statut.
                    n = len(mv) // 2
                    for raw in _s.unpack(f"<{n}h", mv):
                        if raw and raw not in alarm_codes:
                            alarm_codes.append(raw)
            entry = {"times": times, "ports": {}, "uac": None, "freq": None, "temp": None,
                     "alarm_codes": alarm_codes}
            for port, pts in ports.items():
                last = pts[-1] if pts else []
                entry["ports"][port] = {
                    "up": last[0] if len(last) > 0 else None,
                    "ip": last[1] if len(last) > 1 else None,
                    "p": last[2] if len(last) > 2 else None,
                    "e": last[3] if len(last) > 3 else None,  # énergie cumulée jour (Wh)
                }
            if ac_series.get(7):
                entry["uac"] = ac_series[7][-1]
            if ac_series.get(5):
                entry["freq"] = ac_series[5][-1]
            if ac_series.get(6):
                entry["temp"] = ac_series[6][-1]
            result["micros"][mid] = entry
    return result
