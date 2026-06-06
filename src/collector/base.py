"""
base.py — Interface do MetricsCollector.
Todo backend (Mock, Prometheus, DCGM) implementa esta interface.
O restante do sistema nunca sabe qual backend esta em uso.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class GPUJobMetrics:
    job_id: str
    namespace: str
    gpu_type: str
    util_pct: float        # 0-100
    vram_pct: float        # 0-100
    duration_minutes: int
    gpu_count: int
    timestamp: str         # ISO 8601


class BaseMetricsCollector(ABC):

    @abstractmethod
    def collect(self) -> List[GPUJobMetrics]:
        """Retorna metricas de todos os jobs GPU ativos."""
        ...
