"""
prometheus_backend.py — Backend de producao.
Consulta Prometheus via PromQL HTTP API.
A query e identica ao que o MockBackend expoe —
so a origem dos dados muda, nunca o contrato.
"""
from datetime import datetime, timezone
from typing import List

import httpx

from .base import BaseMetricsCollector, GPUJobMetrics


class PrometheusBackend(BaseMetricsCollector):

    def __init__(self, prometheus_url: str = "http://localhost:9090"):
        self.base_url = prometheus_url.rstrip("/")

    def _query(self, promql: str) -> list:
        resp = httpx.get(
            f"{self.base_url}/api/v1/query",
            params={"query": promql},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["data"]["result"]

    def collect(self) -> List[GPUJobMetrics]:
        util_results = self._query("dcgm_gpu_utilization")

        metrics = []
        now = datetime.now(timezone.utc).isoformat()

        for r in util_results:
            labels  = r["metric"]
            job_id  = labels.get("job_id", "unknown")
            namespace = labels.get("namespace", "default")
            gpu_type  = labels.get("gpu_type", "unknown")
            util_pct  = float(r["value"][1])

            vram = self._query(
                f'dcgm_vram_utilization{{job_id="{job_id}"}}'
            )
            duration = self._query(
                f'gpu_job_duration_minutes{{job_id="{job_id}"}}'
            )

            vram_pct     = float(vram[0]["value"][1]) if vram else 0.0
            duration_min = int(float(duration[0]["value"][1])) if duration else 0

            metrics.append(
                GPUJobMetrics(
                    job_id=job_id,
                    namespace=namespace,
                    gpu_type=gpu_type,
                    util_pct=util_pct,
                    vram_pct=vram_pct,
                    duration_minutes=duration_min,
                    gpu_count=1,
                    timestamp=now,
                )
            )

        return metrics
