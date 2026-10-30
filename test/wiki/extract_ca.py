# -*- coding: utf-8 -*-
"""从 Windows 证书存储导出 MITM 代理（SteamTools 等）的根证书，
追加到 PHP 的 CA bundle，让 PHP/composer 能通过 SSL 校验。"""
import ssl
import sys

BUNDLE = sys.argv[1] if len(sys.argv) > 1 else "ca-bundle-extra.crt"
KEYWORDS = ("steam", "watt", "beyonddimension", "mitm", "proxy")

found = {}
for store in ("ROOT", "CA"):
    try:
        for der, enc, trust in ssl.enum_certificates(store):
            import hashlib
            key = hashlib.sha1(der).hexdigest()
            if key in found:
                continue
            pem = (b"-----BEGIN CERTIFICATE-----\n"
                   + __import__("base64").encodebytes(der)
                   + b"-----END CERTIFICATE-----\n")
            # 解析 subject 找关键词
            import subprocess, tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
                f.write(pem)
                tmp = f.name
            try:
                out = subprocess.run(
                    ["openssl", "x509", "-in", tmp, "-noout", "-subject", "-issuer"],
                    capture_output=True, text=True).stdout.lower()
            finally:
                os.unlink(tmp)
            if any(k in out for k in KEYWORDS):
                found[key] = pem.decode("ascii")
    except (OSError, ssl.SSLError):
        continue

with open(BUNDLE, "w", encoding="ascii") as f:
    for pem in found.values():
        f.write(pem + "\n")
print(f"导出 {len(found)} 张证书到 {BUNDLE}")
for pem in found.values():
    print(pem.splitlines()[0], "->", len(pem), "bytes")
