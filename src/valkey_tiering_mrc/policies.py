"""Spill-policy interface and reference implementations.

This module defines a simple `SpillPolicy` interface and a pure-Python
reference `TrueLFUCache` used for tests, sanity checks, and small
experiments. Performance-critical full simulations live in
`valkey_tiering_mrc.simulate` (numba-jitted kernel).

The cache is a *spill/residency simulator*: the SSD/dataset already
contains every value, and DRAM holds a subset. We do not model writes,
TTLs, decay, admission thresholds, or approximate counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class AccessResult:
    hit: bool
    value_size: int


@dataclass
class ResidentEntry:
    key: int
    value_size: int
    freq: int
    last_access: int


class SpillPolicy(Protocol):
    capacity_bytes: int

    def access(self, key: int, value_size: int, t: int) -> AccessResult:
        ...


class TrueLFUCache:
    """Exact LFU with global frequency counters and LRU tie-break.

    Eviction rule:
      - while resident_bytes > capacity_bytes, evict the resident key with
        minimum (freq, last_access). In other words, the least-frequent
        resident key, with ties broken by least-recently-used.

    Frequency counters are global over the entire trace replay; they are
    *not* reset when a key is evicted. There is no decay.

    Note: the eviction picker is an O(resident_count) linear scan. This is
    intentional -- the focus here is experiment correctness, not
    production performance.
    """

    def __init__(self, capacity_bytes: int) -> None:
        if capacity_bytes < 0:
            raise ValueError("capacity_bytes must be >= 0")
        self.capacity_bytes: int = int(capacity_bytes)
        self.resident: dict[int, ResidentEntry] = {}
        self.freq: dict[int, int] = {}
        self.resident_bytes: int = 0

    # ---- introspection helpers (used by tests) ---------------------------

    def is_resident(self, key: int) -> bool:
        return key in self.resident

    def frequency(self, key: int) -> int:
        return self.freq.get(key, 0)

    def num_resident(self) -> int:
        return len(self.resident)

    # ---- main entry point ------------------------------------------------

    def access(self, key: int, value_size: int, t: int) -> AccessResult:
        # Increment global frequency before any eviction decision.
        f = self.freq.get(key, 0) + 1
        self.freq[key] = f

        if key in self.resident:
            entry = self.resident[key]
            entry.freq = f
            entry.last_access = t
            return AccessResult(hit=True, value_size=value_size)

        # Miss path.
        if self.capacity_bytes == 0 or value_size > self.capacity_bytes:
            # Cannot remain resident -- count as a miss but do not admit.
            return AccessResult(hit=False, value_size=value_size)

        # Admit.
        self.resident[key] = ResidentEntry(
            key=key, value_size=value_size, freq=f, last_access=t
        )
        self.resident_bytes += value_size

        # Evict until under capacity. O(resident) per eviction.
        while self.resident_bytes > self.capacity_bytes:
            victim = min(
                self.resident.values(),
                key=lambda e: (e.freq, e.last_access),
            )
            del self.resident[victim.key]
            self.resident_bytes -= victim.value_size

        return AccessResult(hit=False, value_size=value_size)
