"""Named, independent random streams.

Determinism (principle 4) is not achieved by "passing the seed around". It is achieved by giving
every stochastic component its *own* stream derived from the run seed and the component's name:

    rng = streams(seed).get("noise.pink")

Two properties follow, and both matter:

* **Order independence.** Adding a new stochastic component, or drawing a different number of
  values from one component, cannot shift the numbers any other component sees. With a single
  shared generator (or with ``SeedSequence.spawn()``, which is positional) it would.
* **Reproducibility across versions of this code.** The child seed is a BLAKE2b digest of the
  component name, not Python's salted ``hash()``, so it is stable across processes and releases.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

__all__ = ["RngStreams", "child_seed", "streams"]


def child_seed(name: str) -> int:
    """Stable 64-bit integer derived from a component name."""
    return int.from_bytes(hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest(), "big")


@dataclass
class RngStreams:
    """Factory for per-component generators. Caches so repeated ``get`` returns the same stream."""

    seed: int
    _cache: dict[str, np.random.Generator] = field(default_factory=dict, repr=False)

    def get(self, name: str) -> np.random.Generator:
        if name not in self._cache:
            seq = np.random.SeedSequence([self.seed, child_seed(name)])
            self._cache[name] = np.random.default_rng(seq)
        return self._cache[name]

    def fresh(self, name: str) -> np.random.Generator:
        """A generator for ``name`` at its initial state, ignoring the cache.

        Used when a component must be replayed from the start (e.g. regenerating one pass window
        without regenerating the whole run).
        """
        return np.random.default_rng(np.random.SeedSequence([self.seed, child_seed(name)]))


def streams(seed: int) -> RngStreams:
    return RngStreams(seed=int(seed))
