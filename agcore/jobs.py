"""Warteschlange: Aufträge laufen nacheinander im Hintergrund."""
import itertools
import queue
import threading
import time
import traceback
from collections import OrderedDict

from .encoder import Cancelled


class Job:
    _ids = itertools.count(1)

    def __init__(self, kind, title, func, subtitle=""):
        self.id = next(self._ids)
        self.kind = kind            # link | cd | rec | file | stream | watch
        self.title = title
        self.subtitle = subtitle
        self.func = func
        self.status = "wartet"      # wartet | läuft | fertig | fehler | abgebrochen
        self.progress = 0.0
        self.stage = "In der Warteschlange"
        self.outputs = []
        self.error = ""
        self.cancel = threading.Event()
        self.created = time.time()

    def set(self, progress=None, stage=None):
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if stage is not None:
            self.stage = stage

    def snapshot(self):
        return {"id": self.id, "kind": self.kind, "title": self.title, "subtitle": self.subtitle,
                "status": self.status, "progress": round(self.progress, 4), "stage": self.stage,
                "outputs": self.outputs[-50:], "count": len(self.outputs), "error": self.error}


class JobManager:
    def __init__(self, workers=1):
        self.jobs = OrderedDict()
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.listeners = []
        for _ in range(workers):
            threading.Thread(target=self._worker, daemon=True).start()

    def add(self, kind, title, func, subtitle=""):
        job = Job(kind, title, func, subtitle)
        with self.lock:
            self.jobs[job.id] = job
        self.q.put(job)
        return job.id

    def _worker(self):
        while True:
            job = self.q.get()
            if job.cancel.is_set():
                job.status, job.stage = "abgebrochen", "Abgebrochen"
                continue
            job.status, job.stage = "läuft", "Startet …"
            try:
                job.func(job)
                if job.cancel.is_set():
                    raise Cancelled()
                job.status, job.progress = "fertig", 1.0
                if job.stage in ("Startet …", ""):
                    job.stage = "Fertig"
            except Cancelled:
                job.status, job.stage = "abgebrochen", "Abgebrochen"
            except Exception as e:
                job.status, job.error = "fehler", str(e) or e.__class__.__name__
                job.stage = "Fehler"
                try:
                    from .paths import log
                    log.error("Auftrag „%s“ (%s) fehlgeschlagen: %s\n%s", job.title, job.kind, job.error,
                              traceback.format_exc())
                except Exception:
                    pass
            for cb in list(self.listeners):
                try:
                    cb(job)
                except Exception:
                    pass

    def snapshot(self):
        with self.lock:
            return [j.snapshot() for j in reversed(self.jobs.values())]

    def cancel(self, job_id):
        j = self.jobs.get(int(job_id))
        if j and j.status in ("wartet", "läuft"):
            j.cancel.set()
            if j.status == "wartet":
                j.status, j.stage = "abgebrochen", "Abgebrochen"
        return True

    def clear_finished(self):
        with self.lock:
            for k in [k for k, j in self.jobs.items() if j.status in ("fertig", "fehler", "abgebrochen")]:
                del self.jobs[k]
        return True

    def active_count(self):
        return sum(1 for j in self.jobs.values() if j.status in ("wartet", "läuft"))
