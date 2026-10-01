"""Store briefing API keys with Windows DPAPI, never in the repository.

The one-use loopback form allows an already signed-in browser to pass a key to
the local Windows account without placing it in chat, shell arguments, or a
plaintext file. Only the same Windows user can decrypt the saved value.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import parse_qs
import ctypes
from ctypes import wintypes
import os
import sys
import threading


NAMES = {"kpx": "kpx_service_key", "seoul": "seoul_open_data_key"}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, *, protect):
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI에서만 API 키를 보관할 수 있습니다")
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if protect:
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 0x1,
            ctypes.byref(result),
        )
    else:
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x1,
            ctypes.byref(result),
        )
    if not ok:
        raise RuntimeError(f"Windows DPAPI 처리 실패: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
        ctypes.windll.kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def _secret_path(name):
    if name not in NAMES:
        raise ValueError("지원하지 않는 API 키 이름입니다")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Windows LOCALAPPDATA 경로가 없습니다")
    directory = Path(local_app_data) / "RealEstateBriefing" / "secrets"
    return directory / f"{NAMES[name]}.dpapi"


def save_secret(name, value):
    if not value or "\n" in value or "\r" in value or len(value) > 512:
        raise ValueError("API 키 형식이 유효하지 않습니다")
    path = _secret_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _crypt(value.encode("utf-8"), protect=True)
    temporary = path.with_suffix(".dpapi.tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)
    return path


def load_secret(name):
    if name not in NAMES:
        raise ValueError("지원하지 않는 API 키 이름입니다")
    environment_key = os.environ.get(NAMES[name].upper())
    if environment_key:
        return environment_key
    if sys.platform != "win32":
        return None
    path = _secret_path(name)
    if not path.is_file():
        return None
    return _crypt(path.read_bytes(), protect=False).decode("utf-8")


def serve_one_key(name):
    _secret_path(name)
    token = token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return  # URL and key must not appear in terminal logs.

        def do_GET(self):
            html = (
                "<!doctype html><html lang='ko'><meta charset='utf-8'>"
                "<title>API 키 비공개 등록</title><h1>API 키 비공개 등록</h1>"
                "<p>127.0.0.1에서만 열리는 일회용 등록 화면입니다.</p>"
                "<form method='post'>"
                f"<input type='hidden' name='token' value='{token}'>"
                "<label>API 키 <input name='key' type='password' autocomplete='off'></label>"
                "<button type='submit'>이 PC에 암호화 저장</button></form></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            if self.path != "/" or int(self.headers.get("Content-Length", "0")) > 2048:
                self.send_error(400)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            if fields.get("token") != [token]:
                self.send_error(403)
                return
            try:
                save_secret(name, fields.get("key", [""])[0])
                assert load_secret(name) == fields["key"][0]
            except (ValueError, KeyError, RuntimeError, AssertionError):
                self.send_error(500, "Storage failed")
                return
            html = "<html lang='ko'><meta charset='utf-8'><h1>API 키 암호화 저장 완료</h1></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    print(f"LOCAL_KEY_FORM=http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "serve":
        raise SystemExit("사용법: python local_api_secrets.py serve kpx|seoul")
    serve_one_key(sys.argv[2])
