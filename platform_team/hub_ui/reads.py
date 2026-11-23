"""The screen's reads of AWS, kept a few seconds: the page asks again every 5 s, and two pages within that time make
one read. A failed read is not kept. A finished job clears the cache, so the page after it reads AWS again."""
import threading
import time
from typing import Any, Callable


class Cache:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.seconds, self._clock = seconds, clock
        self._lock = threading.Lock()
        self._values: dict[str, tuple[float, Any]] = {}
        self._generation = 0            # counts the clears: a read that began before a clear is not kept

    def get(self, key: str, load: Callable[[], Any]) -> Any:
        """The value read less than `seconds` ago, else load() (kept unless the cache was cleared while it ran)."""
        with self._lock:
            kept = self._values.get(key)
            if kept is not None and self._clock() - kept[0] < self.seconds:
                return kept[1]
            generation, began = self._generation, self._clock()
        value = load()
        with self._lock:
            if generation == self._generation:
                self._values[key] = (began, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._generation += 1
