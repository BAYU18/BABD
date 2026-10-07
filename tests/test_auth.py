"""Dashboard access from other machines: password login with a session cookie, login rate limit,
IP allow list, same-origin writes, and the token that keeps working.

Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd.dashboard.auth import Security, hash_password, verify_password  # noqa: E402
from babd.dashboard.server import make_handler  # noqa: E402

PASSWORD = "correct horse battery"


class PasswordTest(unittest.TestCase):
    def test_hash(self):
        h = hash_password(PASSWORD, iterations=1000)
        self.assertTrue(h.startswith("pbkdf2_sha256$1000$"))
        self.assertTrue(verify_password(PASSWORD, h))
        self.assertFalse(verify_password("wrong password!", h))
        self.assertFalse(verify_password(PASSWORD, "garbage"))
        with self.assertRaises(ValueError):
            hash_password("short")


class AuthServerTest(unittest.TestCase):
    setUp_dash = td.DashboardTest.setUp

    def setUp(self):
        self.setUp_dash()
        self.use(Security(password_hash=hash_password(PASSWORD, iterations=1000), allow="127.0.0.1,10.0.0.0/8",
                          trust_proxy=True))

    def use(self, security):
        self.security = security
        port = self.server.server_port
        self.host = f"127.0.0.1:{port}"
        self.server.RequestHandlerClass = make_handler(self.dash, td.TOKEN, {self.host}, security)

    def req(self, method, path, body=None, headers=None):
        r = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
        for k, v in (headers or {}).items():
            r.add_header(k, v)
        if body is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read() or b"{}")

    def login(self, password=PASSWORD, headers=None):
        return self.req("POST", "/api/login", {"password": password}, headers)

    def test_login_session_logout(self):
        self.assertEqual(self.req("GET", "/api/auth")[2], {"login": True, "authenticated": False})
        status, _, body = self.req("GET", "/api/state")
        self.assertEqual((status, body["login"]), (401, True))
        self.assertEqual(self.login("nope nope nope")[0], 401)
        status, headers, _ = self.login()
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Secure", cookie)  # plain HTTP here
        sid = cookie.split(";")[0]
        self.assertEqual(self.req("GET", "/api/state", headers={"Cookie": sid})[0], 200)
        self.assertEqual(self.req("GET", "/api/auth", headers={"Cookie": sid})[2]["authenticated"], True)
        self.assertEqual(self.req("POST", "/api/logout", headers={"Cookie": sid})[0], 200)
        self.assertEqual(self.req("GET", "/api/state", headers={"Cookie": sid})[0], 401)

    def test_token_still_works(self):
        self.assertEqual(self.req("GET", "/api/state", headers={"X-BABD-Token": td.TOKEN})[0], 200)

    def test_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.login("wrong password here")[0], 401)
        status, headers, body = self.login()  # even the right password waits now
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", headers)
        forged = {"X-Forwarded-For": "10.1.2.3, 127.0.0.1"}  # a forged first entry does not reset the limit
        self.assertEqual(self.login(headers=forged)[0], 429)
        other = {"X-Forwarded-For": "10.1.2.3"}  # another address is not blocked
        self.assertEqual(self.login(headers=other)[0], 200)

    def test_ip_allow_list(self):
        self.assertEqual(self.req("GET", "/", headers={"X-Forwarded-For": "203.0.113.9"})[0], 403)
        self.assertEqual(self.req("GET", "/api/auth", headers={"X-Forwarded-For": "10.9.9.9"})[0], 200)
        # a client cannot forge its address: the proxy's own (last) entry counts
        self.assertEqual(self.req("GET", "/", headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.9"})[0], 403)
        self.use(Security(password_hash="", allow="192.168.0.0/16"))
        self.assertEqual(self.req("GET", "/api/state", headers={"X-BABD-Token": td.TOKEN})[0], 403)

    def test_writes_must_come_from_this_site(self):
        sid = self.login()[1]["Set-Cookie"].split(";")[0]
        evil = {"Cookie": sid, "Origin": "https://evil.example"}
        self.assertEqual(self.req("PUT", "/api/project", {"name": "x"}, evil)[0], 403)
        good = {"Cookie": sid, "Origin": f"http://{self.host}"}
        self.assertEqual(self.req("PUT", "/api/project", {"name": "Shop"}, good)[0], 200)
        self.assertEqual(self.login(headers={"Origin": "https://evil.example"})[0], 403)

    def test_secure_cookie_behind_https_proxy(self):
        _, headers, _ = self.login(headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", headers["Set-Cookie"])
        self.assertIn("Strict-Transport-Security", headers)

    def test_login_off_without_password(self):
        self.use(Security(password_hash=""))
        self.assertEqual(self.req("GET", "/api/auth")[2], {"login": False, "authenticated": False})
        self.assertEqual(self.login()[0], 404)


if __name__ == "__main__":
    unittest.main()
