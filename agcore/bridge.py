"""Kopplung mit anderen Programmen (z. B. Multi Video Downloader).

Läuft SongGrabber bereits, werden neue Aufträge über eine lokale Verbindung (nur 127.0.0.1,
mit Zufalls-Token) an das offene Fenster übergeben, statt ein zweites Fenster zu öffnen.
"""
import json
import os
import secrets
import socket
import socketserver
import threading

from . import paths

IPC_FILE = "ipc.json"


def _ipc_path():
    return os.path.join(paths.data_dir(), IPC_FILE)


def send_to_running(message, timeout=2.0):
    """True, wenn eine laufende Instanz den Auftrag angenommen hat."""
    try:
        with open(_ipc_path(), encoding="utf-8") as f:
            cfg = json.load(f)
        message = dict(message, token=cfg["token"])
        with socket.create_connection(("127.0.0.1", int(cfg["port"])), timeout=timeout) as s:
            s.sendall(json.dumps(message).encode("utf-8") + b"\n")
            return s.recv(16).startswith(b"OK")
    except Exception:
        return False


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            msg = json.loads(self.rfile.readline(1_000_000).decode("utf-8"))
            if msg.get("token") != self.server.token:
                self.wfile.write(b"DENIED")
                return
            self.server.callback(msg)
            self.wfile.write(b"OK")
        except Exception:
            self.wfile.write(b"ERR")


def serve(callback):
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    srv.token = secrets.token_hex(16)
    srv.callback = callback
    with open(_ipc_path(), "w", encoding="utf-8") as f:
        json.dump({"port": srv.server_address[1], "token": srv.token, "pid": os.getpid()}, f)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def shutdown(srv):
    try:
        srv.shutdown()
        os.remove(_ipc_path())
    except Exception:
        pass
