#!/usr/bin/env python3
"""HoymilesCloudApi — client API S-Miles (neapi/euapi), profil S-Miles Home.

Confirmé en live le 13/08/2026 sur un compte S-Miles Home (Argon2id v3,
User-Agent sma/ad/2.10.0/159/0 obligatoire, auth sur euapi.hoymiles.com).
"""
import base64
import hashlib
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


class HoymilesCloudApi:
    def __init__(self, user, password, profile="auto", timeout=20):
        self.user = user
        self.password = password
        self.timeout = timeout
        self.token = None
        self.token_at = 0
        self.method = None
        self.profile_pref = profile
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

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

    def get_realtime(self, sid):
        """count_station_real_data — énergies + puissance instantanée."""
        resp = self._auth_post("/pvm-data/api/0/station/data/count_station_real_data", {"sid": sid})
        return resp.get("data", {})

    def get_burst_uri(self, sid):
        resp = self._auth_post("/pvm/api/0/station/get_sd_uri", {"sid": sid})
        return resp.get("data", {}).get("uri")

    def burst(self, uri, mode=0, mis=None):
        """POST sur l'URI burst. mode 0 = station, mode 3 = micros.
        Nécessite le header Authorization (sinon 400)."""
        body = {"m": mode, "t": 1}
        if mis:
            body["mis"] = mis
        h = {"Content-Type": "application/json", "User-Agent": PROFILES["home"]["ua"],
             "Authorization": self.token}
        r = self.session.post(uri, json=body, headers=h, timeout=self.timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"status": "x", "message": "non-JSON"}

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
            r = self.session.post(url, json={"sid": sid, "date": date}, headers=h, timeout=30)
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
                                        if rf in (1, 2, 3) and rw == 5:
                                            vals.append(_pb_f32(rv))
                                    if vals:
                                        pts.append(vals)
                    if port is not None and pts:
                        ports[port] = pts
                elif mf in (5, 6, 7) and mw == 2:
                    n = len(mv) // 4
                    ac_series[mf] = list(_s.unpack(f"<{n}f", mv))
            entry = {"times": times, "ports": {}, "uac": None, "freq": None, "temp": None}
            for port, pts in ports.items():
                last = pts[-1] if pts else []
                entry["ports"][port] = {
                    "up": last[0] if len(last) > 0 else None,
                    "ip": last[1] if len(last) > 1 else None,
                    "p": last[2] if len(last) > 2 else None,
                }
            if ac_series.get(7):
                entry["uac"] = ac_series[7][-1]
            if ac_series.get(5):
                entry["freq"] = ac_series[5][-1]
            if ac_series.get(6):
                entry["temp"] = ac_series[6][-1]
            result["micros"][mid] = entry
    return result
