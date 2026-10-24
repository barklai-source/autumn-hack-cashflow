"""Bounded in-memory cache for company-scoped API results."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from hashlib import sha256
import json
from threading import RLock
from typing import TypeVar, cast

T = TypeVar("T")
CacheKey = tuple[str, int, float, str, int]


class CompanyResultCache:
    def __init__(self, company_ids: list[str] | None = None, max_entries: int = 512):
        self.company_data_version = {company_id: 0 for company_id in company_ids or []}
        self._values: OrderedDict[CacheKey, object] = OrderedDict()
        self._max_entries = max_entries
        self._lock = RLock()

    @staticmethod
    def _scenario_hash(parameters: dict[str, object]) -> str:
        encoded = json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def get_or_compute(
        self,
        company_id: str,
        horizon: int,
        reserve: float,
        scenario_params: dict[str, object],
        compute: Callable[[], T],
    ) -> T:
        scenario_params_hash = self._scenario_hash(scenario_params)
        with self._lock:
            data_version = self.company_data_version.setdefault(company_id, 0)
            key = (company_id, horizon, float(reserve), scenario_params_hash, data_version)
            if key in self._values:
                self._values.move_to_end(key)
                return cast(T, self._values[key])

        result = compute()
        with self._lock:
            if self.company_data_version.get(company_id, 0) == data_version:
                if key in self._values:
                    self._values.move_to_end(key)
                    return cast(T, self._values[key])
                self._values[key] = result
                self._values.move_to_end(key)
                while len(self._values) > self._max_entries:
                    self._values.popitem(last=False)
                return result
        return self.get_or_compute(company_id, horizon, reserve, scenario_params, compute)

    def invalidate(self, company_id: str) -> int:
        with self._lock:
            version = self.company_data_version.get(company_id, 0) + 1
            self.company_data_version[company_id] = version
            if company_id != "__all__":
                self.company_data_version["__all__"] = self.company_data_version.get("__all__", 0) + 1
            for key in tuple(self._values):
                if key[0] in (company_id, "__all__"):
                    del self._values[key]
            return version
