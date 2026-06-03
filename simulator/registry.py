"""Auto-assign directory numbers to registering devices."""

from __future__ import annotations

import threading


class DeviceRegistry:
    def __init__(self, dn_start: int = 1000):
        self._dn_start = dn_start
        self._next = dn_start
        self._by_device: dict[str, str] = {}
        self._lock = threading.Lock()

    def assign(self, device_name: str) -> str:
        with self._lock:
            if device_name in self._by_device:
                return self._by_device[device_name]
            dn = str(self._next)
            self._next += 1
            self._by_device[device_name] = dn
            return dn

    def get(self, device_name: str) -> str | None:
        return self._by_device.get(device_name)

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._by_device)

    @property
    def next_dn(self) -> int:
        return self._next
