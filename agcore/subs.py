"""Abos: Kanäle/Playlists beobachten und neue Titel automatisch als Audio laden."""
import json
import os
import threading
import time
import uuid

from . import links, paths


def _file():
    return os.path.join(paths.data_dir(), "abos.json")


class Subscriptions:
    def __init__(self, add_download):
        self.add_download = add_download        # callback(url, title, abo) → job id
        self.lock = threading.Lock()
        self.items = []
        self.checking = set()
        try:
            with open(_file(), encoding="utf-8") as f:
                self.items = json.load(f)
        except Exception:
            self.items = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _save(self):
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=1)

    def _fetch(self, url, limit):
        """Neueste Einträge eines Kanals/einer Playlist (ohne Download)."""
        u = url.strip()
        if ("youtube.com/@" in u or "/channel/" in u or "/c/" in u or "/user/" in u) and \
                not u.rstrip("/").endswith(("/videos", "/streams", "/shorts", "/releases")):
            u = u.rstrip("/") + "/videos"
        r = paths.run([links._ytdlp(), "-J", "--flat-playlist", "--no-warnings", "--playlist-end", str(limit), u],
                      timeout=180)
        if r.returncode != 0 or not r.stdout:
            msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError((msg[-1] if msg else "Kanal konnte nicht gelesen werden").replace("ERROR: ", ""))
        d = json.loads(r.stdout.decode("utf-8", "replace"))
        out = []
        for e in d.get("entries") or []:
            if not e or not e.get("id"):
                continue
            vurl = e.get("url") or ""
            if not vurl.startswith("http"):
                vurl = f"https://www.youtube.com/watch?v={e['id']}"
            out.append({"id": e["id"], "title": e.get("title") or vurl, "url": vurl})
        return d.get("title") or d.get("channel") or u, out

    def add(self, url, name="", backfill=0, live_skip=True):
        title, entries = self._fetch(url, max(15, int(backfill or 0)))
        abo = {"id": uuid.uuid4().hex[:10], "url": url.strip(), "name": name.strip() or title, "enabled": True,
               "seen": [e["id"] for e in entries], "added": time.time(), "last_check": time.time(),
               "last_new": 0, "count": 0, "skip_live": bool(live_skip), "error": ""}
        with self.lock:
            if any(a["url"] == abo["url"] for a in self.items):
                raise RuntimeError("Dieser Kanal ist schon abonniert.")
            self.items.append(abo)
            self._save()
        for e in reversed(entries[: int(backfill or 0)]):          # optional die letzten X sofort laden
            self._queue(abo, e)
        return abo

    def _queue(self, abo, e):
        if abo.get("skip_live") and links.live_reason({}, e["title"], e["title"]):
            return False
        self.add_download(e["url"], e["title"], abo["name"])
        abo["count"] = abo.get("count", 0) + 1
        return True

    def check(self, abo_id=None):
        """Prüft ein Abo (oder alle aktiven). Gibt Anzahl neuer Titel zurück."""
        with self.lock:
            todo = [a for a in self.items if (abo_id and a["id"] == abo_id) or (not abo_id and a.get("enabled"))]
        new_total = 0
        for a in todo:
            if a["id"] in self.checking:
                continue
            self.checking.add(a["id"])
            try:
                _, entries = self._fetch(a["url"], 15)
                seen = set(a.get("seen", []))
                new = [e for e in entries if e["id"] not in seen]
                for e in reversed(new):
                    if self._queue(a, e):
                        new_total += 1
                a["seen"] = (list(seen) + [e["id"] for e in new])[-500:]
                a["error"] = ""
                if new:
                    a["last_new"] = time.time()
            except Exception as ex:
                a["error"] = str(ex)[:160]
            finally:
                a["last_check"] = time.time()
                self.checking.discard(a["id"])
                with self.lock:
                    self._save()
        return new_total

    def update(self, abo_id, patch):
        with self.lock:
            for a in self.items:
                if a["id"] == abo_id:
                    a.update({k: v for k, v in patch.items() if k in ("name", "enabled", "skip_live")})
            self._save()
        return True

    def remove(self, abo_id):
        with self.lock:
            self.items = [a for a in self.items if a["id"] != abo_id]
            self._save()
        return True

    def list(self):
        with self.lock:
            return [dict({k: v for k, v in a.items() if k != "seen"}, checking=a["id"] in self.checking)
                    for a in self.items]

    def _loop(self):
        time.sleep(20)                                    # Programmstart nicht ausbremsen
        while True:
            s = paths.settings()
            hours = float(s.get("abo_hours", 6) or 6)
            due = [a for a in self.items if a.get("enabled") and time.time() - a.get("last_check", 0) >= hours * 3600]
            for a in due:
                self.check(a["id"])
            time.sleep(300)


# ---------------------------------------------------------------- Mit Windows starten

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart(enable=None):
    """Ohne Argument: Status. Mit True/False: setzen. Startet minimiert (--minimized)."""
    if not paths.IS_WIN:
        return False
    import sys
    import winreg
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath("main.py")}"'
    cmd = f'"{exe}" --minimized' if getattr(sys, "frozen", False) else f"{exe} --minimized"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        try:                                     # Eintrag unter dem alten Programmnamen übernehmen
            winreg.QueryValueEx(k, paths.OLD_NAME)
            winreg.DeleteValue(k, paths.OLD_NAME)
            winreg.SetValueEx(k, "SongGrabber", 0, winreg.REG_SZ, cmd)
        except FileNotFoundError:
            pass
        if enable is None:
            try:
                winreg.QueryValueEx(k, "SongGrabber")
                return True
            except FileNotFoundError:
                return False
        if enable:
            winreg.SetValueEx(k, "SongGrabber", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "SongGrabber")
            except FileNotFoundError:
                pass
        return bool(enable)
