import queue
import threading
import time
import traceback


class Job:
    def __init__(self, name: str, job_id: int, silent: bool = False):
        self.id = job_id
        self.name = name
        self.silent = silent
        self.progress = 0.0
        self.message = ""
        self.done = False
        self.ok = False
        self.result = None
        self.error = ""
        self.traceback = ""
        self.started = time.time()
        self.finished = 0.0
        self._lock = threading.Lock()

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        with self._lock:
            if progress is not None:
                self.progress = max(0.0, min(1.0, float(progress)))
            if message is not None:
                self.message = str(message)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "name": self.name,
                "progress": self.progress,
                "message": self.message,
                "done": self.done,
                "ok": self.ok,
                "error": self.error,
            }


class JobRunner:
    def __init__(self):
        self._jobs = {}
        self._counter = 0
        self._lock = threading.Lock()
        self._events = queue.Queue()
        self._finished = []

    def run(self, name: str, fn, *args, silent: bool = False, **kwargs) -> Job:
        with self._lock:
            self._counter += 1
            job = Job(name, self._counter, silent=silent)
            self._jobs[job.id] = job

        def worker():
            try:
                result = fn(job, *args, **kwargs)
                job.result = result
                # a returned {"ok": False, "error": ...} is a failure even
                # though nothing raised: the UI reports job outcomes, so a job
                # that failed politely must not read as successful
                if isinstance(result, dict) and "ok" in result:
                    job.ok = bool(result.get("ok"))
                    if not job.ok:
                        job.error = str(result.get("error") or job.error)
                else:
                    job.ok = True
            except Exception as exc:
                job.ok = False
                job.error = f"{type(exc).__name__}: {exc}"
                job.traceback = traceback.format_exc(limit=6)
            finally:
                job.done = True
                job.finished = time.time()
                job.progress = 1.0 if job.ok else job.progress
                self._events.put(job.id)

        threading.Thread(target=worker, name=f"job-{job.id}-{name}", daemon=True).start()
        return job

    def poll(self) -> list:
        finished = []
        while True:
            try:
                job_id = self._events.get_nowait()
            except queue.Empty:
                break
            job = self._jobs.get(job_id)
            if job is not None:
                finished.append(job)
                self._finished.append(job)
        if len(self._finished) > 50:
            self._finished = self._finished[-25:]
            self._jobs = {j.id: j for j in self._finished}
        return finished

    def active(self) -> list:
        return [j for j in self._jobs.values() if not j.done]

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self, limit: int = 10) -> list:
        items = sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)
        return items[:limit]

    def wait(self, job: Job, timeout: float = 30.0, poll: float = 0.05) -> Job:
        deadline = time.time() + timeout
        while not job.done and time.time() < deadline:
            time.sleep(poll)
        return job
