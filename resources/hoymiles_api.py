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
