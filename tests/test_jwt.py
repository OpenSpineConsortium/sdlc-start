"""scripts/jwt.sh signs the App's JWT with openssl.

The token is RS256 over a header and a payload that name the App, dated a
minute back and good for ten from there, and verifies against the key's
public half; the key is generated here at run time and lives in a
temporary folder, so no file of this repository carries one. Without
openssl on PATH the tests skip, since the script has nothing else to sign
with.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/jwt.sh"
HEADER = {"alg": "RS256", "typ": "JWT"}
BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


def decoded(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def openssl(*arguments, **more):
    return subprocess.run(["openssl", *arguments], capture_output=True, check=True, **more)


def run_script(app_id, key, cwd=None, **more_env):
    env = {**os.environ, "APP_ID": app_id, "APP_PRIVATE_KEY": key, **more_env}
    return subprocess.run(["bash", str(SCRIPT)], env=env, cwd=cwd, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("openssl"), "openssl is not on PATH")
class TheToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.root = Path(cls.scratch.name)
        cls.private = cls.root / "key.pem"
        cls.public = cls.root / "key.pub"
        openssl("genrsa", "-out", str(cls.private), "2048")
        openssl("rsa", "-in", str(cls.private), "-pubout", "-out", str(cls.public))
        cls.key = cls.private.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def verified(self, signed, signature):
        """Whether openssl accepts the signature over the signed text with
        the public key."""
        with tempfile.NamedTemporaryFile(dir=self.root, suffix=".sig", delete=False) as handle:
            handle.write(decoded(signature))
        checking = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(self.public), "-signature", handle.name],
                                  input=signed.encode("ascii"), capture_output=True)
        return checking.returncode == 0

    def signed_token(self, key):
        before = int(time.time())
        done = run_script("12345", key)
        after = int(time.time())
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(done.stdout.count("\n"), 1)
        self.assertTrue(done.stdout.endswith("\n"))
        return done.stdout.rstrip("\n"), before, after

    def test_the_token_names_the_app_and_verifies_with_the_public_key(self):
        token, before, after = self.signed_token(self.key)
        header, payload, signature = token.split(".")
        for part in (header, payload, signature):
            self.assertTrue(BASE64URL.fullmatch(part), part)
        self.assertEqual(json.loads(decoded(header)), HEADER)
        claims = json.loads(decoded(payload))
        self.assertEqual(set(claims), {"iat", "exp", "iss"})
        self.assertEqual(claims["iss"], "12345")
        self.assertGreaterEqual(claims["iat"], before - 60)
        self.assertLessEqual(claims["iat"], after - 50)
        self.assertEqual(claims["exp"] - claims["iat"], 600)
        self.assertTrue(self.verified(f"{header}.{payload}", signature))
        self.assertFalse(self.verified(f"{header}.{payload}x", signature))

    def test_the_header_is_the_fixed_one(self):
        """The header is a constant, so its encoding is too."""
        token, _, _ = self.signed_token(self.key)
        header = base64.urlsafe_b64encode(json.dumps(HEADER, separators=(",", ":")).encode("ascii")).rstrip(b"=")
        self.assertEqual(token.split(".")[0], header.decode("ascii"))

    def test_a_key_in_the_form_github_downloads_signs_too(self):
        """GitHub hands out PKCS#1 keys (BEGIN RSA PRIVATE KEY); OpenSSL 3
        generates PKCS#8 ones. Both sign."""
        traditional = self.root / "key1.pem"
        converting = subprocess.run(["openssl", "rsa", "-in", str(self.private), "-traditional", "-out", str(traditional)],
                                    capture_output=True)
        if converting.returncode != 0:
            self.skipTest("this openssl writes no PKCS#1 key")
        key = traditional.read_text(encoding="utf-8")
        self.assertIn("BEGIN RSA PRIVATE KEY", key)
        token, _, _ = self.signed_token(key)
        header, payload, signature = token.split(".")
        self.assertTrue(self.verified(f"{header}.{payload}", signature))

    def test_a_key_without_its_final_newline_signs_too(self):
        """A secret pasted into GitHub may lose the newline at its end."""
        token, _, _ = self.signed_token(self.key.rstrip("\n"))
        header, payload, signature = token.split(".")
        self.assertTrue(self.verified(f"{header}.{payload}", signature))

    def test_a_missing_id_or_key_exits_2_and_prints_nothing(self):
        for app_id, key in (("", self.key), ("12345", ""), ("", "")):
            with self.subTest(app_id=app_id, key=bool(key)):
                done = run_script(app_id, key)
                self.assertEqual((done.returncode, done.stdout), (2, ""))
                self.assertEqual(done.stderr.count("\n"), 1)
                self.assertIn("APP_ID", done.stderr)

    def test_an_id_that_would_break_the_json_is_refused(self):
        """The whole value is matched: a newline inside or at the end of
        the id would pass a check made line by line and land in the JSON."""
        for app_id in ('12345"}', "12345\n", "123\n45", " 12345", "12345 "):
            with self.subTest(app_id=app_id):
                done = run_script(app_id, self.key)
                self.assertEqual((done.returncode, done.stdout), (2, ""))
                self.assertEqual(done.stderr.count("\n"), 1)
                self.assertIn("APP_ID", done.stderr)
        done = run_script("Iv1.0123456789abcdef", self.key)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(decoded(done.stdout.split(".")[1]))["iss"], "Iv1.0123456789abcdef")

    def test_a_key_that_is_not_one_fails_without_a_token(self):
        done = run_script("12345", "-----BEGIN RSA PRIVATE KEY-----\nnot a key\n-----END RSA PRIVATE KEY-----\n")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")

    def test_the_key_leaves_no_file_behind(self):
        """Process substitution hands the key to openssl; nothing is written.
        The script runs in a fresh empty folder that is also its temporary
        folder, so a key written anywhere it could write would be found."""
        folder = self.root / "where-the-script-runs"
        folder.mkdir()
        where = str(folder)
        done = run_script("12345", self.key, cwd=where, TMPDIR=where, TMP=where, TEMP=where)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(done.stdout.count("."), 2)
        self.assertEqual(list(folder.iterdir()), [])


class TheScript(unittest.TestCase):
    def test_the_script_parses_and_says_how_it_is_called(self):
        checked = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual((checked.returncode, checked.stderr), (0, ""))
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail\n", text)
        self.assertIn("Usage: APP_ID=... APP_PRIVATE_KEY=... bash scripts/jwt.sh", text)
        self.assertIn('-sign <(printf \'%s\\n\' "$APP_PRIVATE_KEY")', text)


if __name__ == "__main__":
    unittest.main()
