"""Métricas do processo atual, sem confundi-las com saúde do host ou do MLflow."""

from __future__ import annotations

import threading
import time

import psutil


class ProcessResources:
    """Amostra CPU/RSS no início, durante e no fim de uma operação curta."""

    def __init__(self, interval_seconds: float = 0.05) -> None:
        if interval_seconds <= 0:
            raise ValueError("Intervalo de amostragem deve ser positivo")
        self.interval_seconds = interval_seconds
        self.process = psutil.Process()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rss_peak = 0
        self._cpu_start = 0.0
        self._started = 0.0

    def _sample(self) -> int:
        rss = int(self.process.memory_info().rss)
        self._rss_peak = max(self._rss_peak, rss)
        return rss

    def _sample_loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self._sample()
            except (psutil.Error, OSError):
                return

    def start(self) -> None:
        self._started = time.perf_counter()
        self._cpu_start = sum(self.process.cpu_times()[:2])
        self._sample()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def finish(self) -> dict[str, float | int | str]:
        elapsed = time.perf_counter() - self._started
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds * 2)
        try:
            self._sample()
            cpu_seconds = max(0.0, sum(self.process.cpu_times()[:2]) - self._cpu_start)
        except (psutil.Error, OSError):
            cpu_seconds = 0.0
        return {
            "duration_seconds": elapsed,
            "cpu_seconds": cpu_seconds,
            "rss_peak_bytes": self._rss_peak,
            "resource_scope": "process_and_children_excluded",
            "rss_sampling_interval_seconds": self.interval_seconds,
        }
