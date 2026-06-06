"""
mock_backend.py — Backend de simulacao local.
Dois papeis:
  1. MockBackend: le scenarios.yaml direto (testes e dev sem Docker)
  2. GPUMockPrometheusCollector: injeta cenarios no Prometheus local
     para que o PrometheusBackend use PromQL igual ao de producao.
"""
import time
from datetime import datetime, timezone
from typing import List

import yaml
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, REGISTRY

from .base import BaseMetricsCollector, GPUJobMetrics


class GPUMockPrometheusCollector:
    """
    Custom Collector: injeta cenarios do YAML no Prometheus.
    O MetricsCollector faz PromQL igual em dev e producao.
    So a origem dos dados muda, nunca a query.
    """

    def __init__(self, scenarios_path: str):
        self.scenarios_path = scenarios_path

    def collect(self):
        with open(self.scenarios_path) as f:
            data = yaml.safe_load(f)

        jobs = data.get("jobs", {})

        util_metric = GaugeMetricFamily(
            "dcgm_gpu_utilization",
            "GPU utilization percent",
            labels=["job_id", "namespace", "gpu_type"],
        )
        vram_metric = GaugeMetricFamily(
            "dcgm_vram_utilization",
            "VRAM utilization percent",
            labels=["job_id", "namespace", "gpu_type"],
        )
        duration_metric = GaugeMetricFamily(
            "gpu_job_duration_minutes",
            "Job running duration in minutes",
            labels=["job_id", "namespace"],
        )

        for job_id, m in jobs.items():
            labels = [job_id, m["namespace"], m["gpu_type"]]
            util_metric.add_metric(labels, m["util_pct"])
            vram_metric.add_metric(labels, m["vram_pct"])
            duration_metric.add_metric(
                [job_id, m["namespace"]], m["duration_minutes"]
            )

        yield util_metric
        yield vram_metric
        yield duration_metric


class MockBackend(BaseMetricsCollector):
    """
    Le scenarios.yaml diretamente.
    Usado em testes unitarios e dev sem Docker.
    """

    def __init__(self, scenarios_path: str = "config/scenarios.yaml"):
        self.scenarios_path = scenarios_path

    def collect(self) -> List[GPUJobMetrics]:
        with open(self.scenarios_path) as f:
            data = yaml.safe_load(f)

        now = datetime.now(timezone.utc).isoformat()
        metrics = []

        for job_id, m in data.get("jobs", {}).items():
            metrics.append(
                GPUJobMetrics(
                    job_id=job_id,
                    namespace=m["namespace"],
                    gpu_type=m["gpu_type"],
                    util_pct=float(m["util_pct"]),
                    vram_pct=float(m["vram_pct"]),
                    duration_minutes=int(m["duration_minutes"]),
                    gpu_count=int(m["gpu_count"]),
                    timestamp=now,
                )
            )
        return metrics


def register_mock_collector(
    scenarios_path: str = "config/scenarios.yaml",
    port: int = 8000,
):
    """
    Registra o Custom Collector e sobe servidor HTTP.
    Chamado pelo docker-compose via start_mock.py.
    """
    REGISTRY.register(GPUMockPrometheusCollector(scenarios_path))
    start_http_server(port)
    print(f"Mock Prometheus exporter rodando na porta {port}")
    while True:
        time.sleep(10)
