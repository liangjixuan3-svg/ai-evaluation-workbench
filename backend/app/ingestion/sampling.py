from __future__ import annotations

import random
from dataclasses import dataclass
from math import floor
from uuid import UUID

from app.ingestion.contracts import SampleCandidate


@dataclass(frozen=True)
class SamplingPolicy:
    daily_budget: int
    random_ratio: float
    scenario_ratio: float
    risk_ratio: float
    priority_scenarios: frozenset[str]


def select_sample(items: list[SampleCandidate], policy: SamplingPolicy, seed: int) -> list[UUID]:
    if policy.daily_budget <= 0:
        return []
    if min(policy.random_ratio, policy.scenario_ratio, policy.risk_ratio) < 0:
        raise ValueError("sampling ratios must be non-negative")

    candidates = _deduplicate(items)
    buckets = {
        "risk": [item for item in candidates if item.is_risk],
        "scenario": [
            item
            for item in candidates
            if not item.is_risk and item.scenario in policy.priority_scenarios
        ],
        "random": [
            item
            for item in candidates
            if not item.is_risk and item.scenario not in policy.priority_scenarios
        ],
    }
    generator = random.Random(seed)
    for bucket in buckets.values():
        generator.shuffle(bucket)

    ratios = {
        "risk": policy.risk_ratio,
        "scenario": policy.scenario_ratio,
        "random": policy.random_ratio,
    }
    limits = _bucket_limits(policy.daily_budget, ratios)
    selected: list[UUID] = []
    for bucket_name in ("risk", "scenario", "random"):
        remaining = policy.daily_budget - len(selected)
        if remaining == 0:
            return selected
        selected.extend(
            item.id for item in buckets[bucket_name][: min(limits[bucket_name], remaining)]
        )

    # Empty buckets return their unused quota to higher-priority eligible items first.
    selected_ids = set(selected)
    for bucket_name in ("risk", "scenario", "random"):
        for item in buckets[bucket_name]:
            if len(selected) == policy.daily_budget:
                return selected
            if item.id not in selected_ids:
                selected.append(item.id)
                selected_ids.add(item.id)
    return selected


def _deduplicate(items: list[SampleCandidate]) -> list[SampleCandidate]:
    candidates: dict[UUID, SampleCandidate] = {}
    for item in items:
        existing = candidates.get(item.id)
        if existing is None or (item.is_risk and not existing.is_risk):
            candidates[item.id] = item
    return [candidates[item_id] for item_id in sorted(candidates, key=str)]


def _bucket_limits(daily_budget: int, ratios: dict[str, float]) -> dict[str, int]:
    limits = {bucket: floor(daily_budget * ratio) for bucket, ratio in ratios.items()}
    remaining = max(0, daily_budget - sum(limits.values()))
    remainders = sorted(
        ratios,
        key=lambda bucket: (
            -(daily_budget * ratios[bucket] - limits[bucket]),
            -_priority(bucket),
        ),
    )
    for bucket in remainders:
        if remaining == 0:
            break
        limits[bucket] += 1
        remaining -= 1
    return limits


def _priority(bucket: str) -> int:
    return {"risk": 3, "scenario": 2, "random": 1}[bucket]
