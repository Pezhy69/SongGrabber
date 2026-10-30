"""Bibliothek aufräumen: doppelte Titel, fehlende Angaben (Cover, Album, Genre, Jahr), leere Ordner.

Alles wird zuerst nur geprüft und als Vorschlag gezeigt – gelöscht oder geändert wird erst nach Bestätigung.
"""
import os
import re
import threading

from . import metadata, paths

LOSSLESS = {".flac", ".wav", ".aiff", ".aif", ".ape", ".alac"}
JUNK = {"desktop.ini", "thumbs.db", ".ds_store", "folder.jpg", "cover.jpg", "front.jpg", "albumart.jpg",
        "albumartsmall.jpg", "folder.png", "cover.png"}
_VER = re.compile(r"\s*[\(\[][^\)\]]*(remaster|official|audio|video|hd|hq|explicit|clean|lyrics?|visuali[sz]er)[^\)\]]*[\)\]]", re.I)


def _key(it):
    a = metadata.norm(it.get("artist") or "")
    t = metadata.norm(_VER.sub("", it.get("title") or ""))
    return (a, t) if a and t else None


def _quality(path):
    """→ (punkte, beschreibung, hat_cover)"""
    ext = os.path.splitext(path)[1].lower()
    desc, score, cover = ext[1:].upper(), 0, False
    try:
        import mutagen
        f = mutagen.File(path)
        info = getattr(f, "info", None)
        br = int(getattr(info, "bitrate", 0) or 0) // 1000
        bits = int(getattr(info, "bits_per_sample", 0) or 0)
        rate = int(getattr(info, "sample_rate", 0) or 0)
        if ext in LOSSLESS:
            score = 2000 + bits * 10 + rate / 1000
            desc += f" · {bits or 16} Bit / {rate / 1000:g} kHz" if rate else ""
        else:
            score = br
            desc += f" · {br} kbps" if br else ""
        tags = getattr(f, "tags", None)
        if tags is not None:
            if hasattr(tags, "getall"):
                cover = bool(tags.getall("APIC"))
            elif "covr" in tags:
                cover = True
            elif "metadata_block_picture" in tags:
                cover = True
        cover = cover or bool(getattr(f, "pictures", None))
    except Exception:
        pass
    return score, desc, cover


class Cleanup:
    def __init__(self):
        self.running = False
        self.progress = (0, 0)
        self.result = None
        self.error = ""

    def start(self, items):
        if self.running:
            return False
        self.running, self.result, self.error = True, None, ""
        threading.Thread(target=self._run, args=(list(items),), daemon=True).start()
        return True

    def status(self):
        return {"running": self.running, "done": self.progress[0], "total": self.progress[1],
                "result": self.result, "error": self.error}

    def _run(self, items):
        try:
            self.progress = (0, len(items))
            info = {}
            for i, it in enumerate(items, 1):
                p = it["path"]
                if os.path.isfile(p):
                    score, desc, cover = _quality(p)
                    info[p] = {"score": score, "q": desc, "cover": cover, "size": it.get("size") or 0}
                self.progress = (i, len(items))
            # doppelte Titel
            groups = {}
            for it in items:
                k = _key(it)
                if k and it["path"] in info:
                    groups.setdefault(k, []).append(it)
            dups, free = [], 0
            for k, lst in groups.items():
                if len(lst) < 2:
                    continue
                # gleiche Länge (±4 s) – sonst ist es eher eine andere Fassung (Live, Remix …)
                lst.sort(key=lambda x: x.get("duration") or 0)
                runs, cur = [], [lst[0]]
                for x in lst[1:]:
                    d0, d1 = cur[-1].get("duration") or 0, x.get("duration") or 0
                    if not d0 or not d1 or abs(d0 - d1) <= 4:
                        cur.append(x)
                    else:
                        runs.append(cur)
                        cur = [x]
                runs.append(cur)
                for r in runs:
                    if len(r) < 2:
                        continue
                    files = []
                    for x in r:
                        q = info[x["path"]]
                        files.append({"path": x["path"], "q": q["q"], "score": q["score"], "size": q["size"],
                                      "cover": q["cover"], "album": x.get("album") or "", "duration": x.get("duration") or 0})
                    files.sort(key=lambda f: (f["score"], f["cover"], bool(f["album"]), f["size"]), reverse=True)
                    files[0]["keep"] = True
                    free += sum(f["size"] for f in files[1:])
                    best = next(x for x in r if x["path"] == files[0]["path"])
                    dups.append({"artist": best.get("artist"), "title": best.get("title"), "files": files})
            dups.sort(key=lambda g: (g["artist"] or "").lower())
            # fehlende Angaben
            missing = {"cover": [], "album": [], "genre": [], "year": []}
            for it in items:
                p = it["path"]
                if p not in info:
                    continue
                if not info[p]["cover"]:
                    missing["cover"].append(p)
                for k in ("album", "genre", "year"):
                    if not (it.get(k) or "").strip():
                        missing[k].append(p)
            fill = sorted(set(sum(missing.values(), [])))
            self.result = {"dups": dups, "dup_free": free, "missing": {k: len(v) for k, v in missing.items()},
                           "fill": fill, "empty": empty_dirs()}
        except Exception as e:
            paths.log.exception("Aufräumen")
            self.error = str(e)
        finally:
            self.running = False


def empty_dirs(root=None):
    """Ordner ohne Musik (nur leer oder mit Resten wie folder.jpg/desktop.ini) – tiefste zuerst."""
    root = os.path.abspath(root or paths.settings()["output_dir"])
    out = []
    if not os.path.isdir(root):
        return out
    has = {}
    for d, subs, names in os.walk(root, topdown=False):
        if os.path.basename(d).startswith("_") or os.path.basename(d) == "Playlists":
            has[d] = True
            continue
        keep = any(n.lower() not in JUNK for n in names)
        keep = keep or any(has.get(os.path.join(d, s), True) for s in subs)
        has[d] = keep
        if not keep and d != root:
            out.append(d)
    return out


def remove_dirs(dirs):
    root = os.path.abspath(paths.settings()["output_dir"])
    done = 0
    for d in sorted(dirs, key=len, reverse=True):
        d = os.path.abspath(d)
        if not d.startswith(root + os.sep) or not os.path.isdir(d):
            continue
        try:
            for n in os.listdir(d):
                f = os.path.join(d, n)
                if os.path.isfile(f) and n.lower() in JUNK:
                    os.remove(f)
            os.rmdir(d)
            done += 1
        except OSError:
            pass
    return done
