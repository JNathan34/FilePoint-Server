"""Opt-in smoke test with a disposable FileBrowser instance. Run on the server as an administrator."""

import hashlib
import http.client
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import server


IMAGE = "gtstef/filebrowser:1.5.5-stable"
CONFIG = """server:
  listen: "0.0.0.0"
  port: 80
  database: "/test/database.db"
  cacheDir: "/test/cache"
  sources:
    - name: "Documents"
      path: "/test/storage"
      config:
        defaultEnabled: true
auth:
  methods:
    password:
      enabled: true
userDefaults:
  account:
    permissions:
      api: true
      create: true
      modify: true
      download: true
"""


def call(port, method, path, headers=None, data=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request(method, path, headers=headers or {}, body=data)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def main():
    with tempfile.TemporaryDirectory(prefix="filepoint-native-test-") as temporary:
        root = Path(temporary)
        storage = root / "storage"
        storage.mkdir()
        (storage / "Restricted").mkdir()
        (root / "config.yaml").write_text(CONFIG)
        password = secrets.token_urlsafe(24)
        docker = ["docker", "run", "--rm", "--user", "0:0", "-v", f"{root}:/test"]
        setup = subprocess.run(docker + [IMAGE, "set", "-u", f"tester,{password}",
                               "-c", "/test/config.yaml"], capture_output=True, text=True)
        if setup.returncode:
            raise RuntimeError((setup.stdout + setup.stderr).replace(password, "[test password]")[-1800:])
        subprocess.run(docker + [IMAGE, "set", "rule", "-c", "/test/config.yaml", "-s", "Documents",
                                  "-p", "/Restricted/", "-r", "user", "-v", "tester"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        container = subprocess.check_output(
            docker + ["-d", "-p", "127.0.0.1::80", IMAGE, "-c", "/test/config.yaml"], text=True
        ).strip()
        try:
            address = subprocess.check_output(["docker", "port", container, "80/tcp"], text=True).strip()
            upstream_port = int(address.rsplit(":", 1)[1])
            login = None
            for _ in range(45):
                try:
                    status, login = call(upstream_port, "POST", "/api/auth/login?username=tester",
                                         {"X-Password": password})
                    if status == 200:
                        break
                    login = None
                except OSError:
                    pass
                time.sleep(1)
            if not login:
                raise RuntimeError("The isolated FileBrowser login was not ready.")

            server.UPSTREAM_HOST = "127.0.0.1"
            server.UPSTREAM_PORT = upstream_port
            server.STORAGE_MAP = root / "storage-map.json"
            server.NATIVE_WRITE_CONFIG = root / "native-write-sources.json"
            server.STORAGE_MAP.write_text(json.dumps({"Documents": str(storage)}))
            server.NATIVE_WRITE_CONFIG.write_text('["Documents"]')
            with server.ProxyServer(("127.0.0.1", 0), server.Handler) as proxy:
                thread = threading.Thread(target=proxy.serve_forever, daemon=True)
                thread.start()
                try:
                    run_checks(proxy.server_port, login.decode().strip(), storage)
                finally:
                    proxy.shutdown()
                    thread.join()
        finally:
            subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, check=False)


def run_checks(port, token, storage):
    endpoint = "/__foldericons/native-files"
    headers = {"Authorization": "Bearer " + token}

    def send(method, expected, data=None, **query):
        path = endpoint + ("?" + urlencode(query) if query else "")
        status, body = call(port, method, path, headers, data)
        if status != expected:
            raise RuntimeError(f"{method} {list(query)} returned HTTP {status}: {body.decode()[:200]}")
        return json.loads(body)

    assert call(port, "GET", endpoint)[0] == 401
    assert send("GET", 200) == {"protocol": 1, "sources": ["Documents"]}
    assert send("POST", 201, source="Documents", path="/New folder", mode="directory")["created"]
    assert (storage / "New folder").is_dir()
    send("POST", 400, source="Documents", path="/../escape", mode="create")
    send("POST", 403, source="Other", path="/test.bin", mode="create")
    send("POST", 403, source="Documents", path="/Restricted/test.bin", mode="create")
    first = send("POST", 201, source="Documents", path="/New folder/test.bin", mode="create")
    conflicting = send("POST", 201, source="Documents", path="/New folder/test.bin", mode="create")
    chunk = bytes(range(256)) * 16384
    send("PUT", 200, data=chunk, upload=first["upload"], offset=0)
    send("PUT", 200, data=b"tail", upload=first["upload"], offset=len(chunk))
    target = storage / "New folder" / "test.bin"
    assert not target.exists()
    send("PATCH", 200, upload=first["upload"], length=len(chunk) + 4)
    assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(chunk + b"tail").digest()
    send("PATCH", 409, upload=conflicting["upload"], length=0)
    send("DELETE", 200, upload=conflicting["upload"])
    edit = send("POST", 201, source="Documents", path="/New folder/test.bin", mode="edit")
    send("PUT", 200, data=b"updated", upload=edit["upload"], offset=0)
    assert target.stat().st_size == len(chunk) + 4
    send("PATCH", 200, upload=edit["upload"], length=7)
    assert target.read_bytes() == b"updated"
    send("POST", 200, source="Documents", path="/New folder/test.bin",
         destination="/New folder/renamed.bin", mode="rename", replace="false")
    assert not target.exists() and target.with_name("renamed.bin").read_bytes() == b"updated"
    listing = "/api/resources?" + urlencode({"source": "Documents", "path": "/New folder"})
    for _ in range(25):
        status, body = call(port, "GET", listing, headers)
        if status == 200 and any(item["name"] == "renamed.bin" for item in json.loads(body).get("files", [])):
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("The regular FileBrowser listing did not pick up the committed file.")
    if "--large" in sys.argv:
        length = 1024**3
        if shutil.disk_usage(storage).free < length * 2:
            raise RuntimeError("The isolated test location needs 2 GiB free for the large file check.")
        pending = send("POST", 201, source="Documents", path="/large.bin", mode="create")
        expected = hashlib.sha256()
        for offset in range(0, length, len(chunk)):
            send("PUT", 200, data=chunk, upload=pending["upload"], offset=offset)
            expected.update(chunk)
        send("PATCH", 200, upload=pending["upload"], length=length)
        with (storage / "large.bin").open("rb") as file:
            assert hashlib.file_digest(file, "sha256").digest() == expected.digest()
        print("Passed a verified 1 GiB upload.")
    print("Passed real FileBrowser authorization, folder creation, atomic chunked upload, conflicts and edits.")


if __name__ == "__main__":
    main()
