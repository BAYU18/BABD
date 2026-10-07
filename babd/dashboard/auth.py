"""Dashboard access when it is reachable from other machines.

  - password login: `babd set-password` stores a PBKDF2 hash in .env (BABD_DASHBOARD_PASSWORD_HASH);
    logging in gives an HttpOnly, SameSite=Strict session cookie (Secure over HTTPS)
  - too many wrong passwords from one address: that address waits (rate limit)
  - `--allow-ip`: only these addresses / networks may connect at all
  - `--public-url`: the Host header must be that site (stops DNS-rebinding pages)
  - `--trust-proxy`: behind a reverse proxy (Caddy, nginx) that terminates HTTPS, take the client
    address from X-Forwarded-For and HTTPS from X-Forwarded-Proto

The start-up token keeps working (for the URL printed in the terminal and for scripts).
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time

HASH_ENV = "BABD_DASHBOARD_PASSWORD_HASH"
SESSION_COOKIE = "babd_session"
SESSION_HOURS = 12
ITERATIONS = 310_000


def hash_password(password, iterations=ITERATIONS, salt=None):
    if len(password or "") < 10:
        raise ValueError("use a password of at least 10 characters")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password, stored):
    try:
        algo, iterations, salt, digest = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", (password or "").encode(), salt.encode(), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc, digest)


class Sessions:
    def __init__(self, hours=SESSION_HOURS):
        self.ttl = hours * 3600
        self.items = {}
        self.lock = threading.Lock()

    def create(self):
        sid = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            self.items = {k: v for k, v in self.items.items() if v > now}
            self.items[sid] = now + self.ttl
        return sid

    def valid(self, sid):
        with self.lock:
            exp = self.items.get(sid or "")
            return bool(exp and exp > time.time())

    def drop(self, sid):
        with self.lock:
            self.items.pop(sid or "", None)


class LoginLimiter:
    """At most `max_failures` wrong passwords per address in `window` seconds."""

    def __init__(self, max_failures=5, window=600):
        self.max, self.window = max_failures, window
        self.failures = {}
        self.lock = threading.Lock()

    def blocked_for(self, ip):
        with self.lock:
            now = time.time()
            recent = [t for t in self.failures.get(ip, []) if t > now - self.window]
            self.failures[ip] = recent
            return int(recent[0] + self.window - now) + 1 if len(recent) >= self.max else 0

    def fail(self, ip):
        with self.lock:
            self.failures.setdefault(ip, []).append(time.time())

    def reset(self, ip):
        with self.lock:
            self.failures.pop(ip, None)


def parse_networks(spec):
    nets = []
    for part in (spec or "").replace(",", " ").split():
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError as e:
            raise ValueError(f"--allow-ip: {part!r} is not an address or network") from e
    return nets


class Security:
    def __init__(self, password_hash=None, allow=None, trust_proxy=False, https=False):
        self.password_hash = password_hash if password_hash is not None else os.environ.get(HASH_ENV) or None
        self.networks = parse_networks(allow) if isinstance(allow, str) else (allow or [])
        self.trust_proxy = trust_proxy
        self.https = https
        self.sessions = Sessions()
        self.limiter = LoginLimiter()

    @property
    def login_enabled(self):
        return bool(self.password_hash)

    def client_ip(self, handler):
        ip = handler.client_address[0]
        if self.trust_proxy:
            fwd = handler.headers.get("X-Forwarded-For")
            if fwd:
                ip = fwd.split(",")[0].strip()
        return ip

    def ip_allowed(self, ip):
        if not self.networks:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in n for n in self.networks)

    def is_https(self, handler):
        return self.https or (self.trust_proxy and handler.headers.get("X-Forwarded-Proto", "").lower() == "https")

    def session_of(self, handler):
        for part in (handler.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == SESSION_COOKIE:
                return v
        return None

    def cookie(self, handler, sid, max_age=SESSION_HOURS * 3600):
        attrs = f"{SESSION_COOKIE}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        return attrs + ("; Secure" if self.is_https(handler) else "")
