"""
policy_engine.py — Camada deterministica.
Avalia metricas contra policies.yaml e decide:
  AUTO_ACT  : score alto, age sem LLM
  CALL_LLM  : score medio, passa para o LLM
  IGNORE    : score baixo, nao faz nada
  BLOCKED   : circuit breaker ativo
Nunca levanta excecao — sempre retorna uma Decision.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import yaml

from ..collector.base import GPUJobMetrics


class DecisionRoute(str, Enum):
    AUTO_ACT = "auto_act"
    CALL_LLM = "call_llm"
    IGNORE   = "ignore"
    BLOCKED  = "blocked"


@dataclass
class Decision:
    job_id: str
    namespace: str
    route: DecisionRoute
    score: float
    trigger: str                # "idle" | "vram_anomaly" | "none"
    suggested_action: str       # "pause_job" | "recommend" | "noop"
    context: dict               # metricas que geraram a decisao
    dry_run: bool
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def idle_score(util_pct: float, duration_minutes: int) -> float:
    """
    Score de ociosidade: intensidade + persistencia.
    util=2%,  210min -> ~0.93  (AUTO_ACT)
    util=4%,   95min -> ~0.76  (CALL_LLM)
    util=13%,  38min -> ~0.21  (IGNORE)
    """
    intensity   = max(0.0, (15.0 - util_pct) / 15.0)
    persistence = min(1.0, duration_minutes / 120.0)
    return round(intensity * 0.6 + persistence * 0.4, 3)


def vram_score(vram_pct: float, duration_minutes: int) -> float:
    """
    Score de anomalia de VRAM.
    Saturado acima de 95% de utilizacao.
    """
    intensity   = max(0.0, (vram_pct - 95.0) / 5.0)
    persistence = min(1.0, duration_minutes / 30.0)
    return round(intensity * 0.7 + persistence * 0.3, 3)


class PolicyEngine:

    def __init__(self, policies_path: str = "config/policies.yaml"):
        self.policies_path = policies_path
        self._policies = None
        self._mtime = 0
        self._action_counts: dict = {}

    def _load_policies(self) -> dict:
        """Recarrega o YAML se o arquivo mudou — hot reload."""
        mtime = os.path.getmtime(self.policies_path)
        if mtime != self._mtime:
            with open(self.policies_path) as f:
                self._policies = yaml.safe_load(f)
            self._mtime = mtime
        return self._policies

    def _is_circuit_open(self, p: dict) -> bool:
        """True se o limite de acoes da hora foi atingido."""
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        max_actions = p["global"]["circuit_breaker"]["max_actions_per_hour"]
        return self._action_counts.get(hour_key, 0) >= max_actions

    def _register_action(self):
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        self._action_counts[hour_key] = self._action_counts.get(hour_key, 0) + 1

    def _team_allows_auto_pause(self, namespace: str, p: dict) -> bool:
        for team in p.get("teams", []):
            if team["namespace"] == namespace:
                return team.get("allow_auto_pause", False)
        return False

    def _gpu_cost_per_hour(self, gpu_type: str, p: dict) -> float:
        costs = p.get("gpu_cost", {}).get("usd_per_hour", {})
        return costs.get(gpu_type, costs.get("default", 2.50))

    def evaluate(self, metrics: GPUJobMetrics) -> Decision:
        p       = self._load_policies()
        dry_run = p["global"].get("dry_run", True)
        thr     = p["thresholds"]

        cost_per_hour = (
            self._gpu_cost_per_hour(metrics.gpu_type, p) * metrics.gpu_count
        )
        context = {
            "util_pct":          metrics.util_pct,
            "vram_pct":          metrics.vram_pct,
            "duration_minutes":  metrics.duration_minutes,
            "gpu_count":         metrics.gpu_count,
            "gpu_type":          metrics.gpu_type,
            "cost_usd_per_hour": cost_per_hour,
        }

        # 1. Anomalia de VRAM — alta prioridade
        if (
            metrics.vram_pct > thr["vram_anomaly"]["util_pct_above"]
            and metrics.duration_minutes >= thr["vram_anomaly"]["duration_minutes"]
        ):
            score = vram_score(metrics.vram_pct, metrics.duration_minutes)
            return self._route(
                metrics, score, "vram_anomaly", "recommend", context, dry_run, p
            )

        # 2. GPU ociosa
        if (
            metrics.util_pct < thr["idle"]["util_pct_below"]
            and metrics.duration_minutes >= thr["idle"]["duration_minutes"]
        ):
            score = idle_score(metrics.util_pct, metrics.duration_minutes)

            # Equipe sem auto-pause vai direto para LLM
            if not self._team_allows_auto_pause(metrics.namespace, p):
                return Decision(
                    job_id=metrics.job_id,
                    namespace=metrics.namespace,
                    route=DecisionRoute.CALL_LLM,
                    score=score,
                    trigger="idle",
                    suggested_action="recommend",
                    context=context,
                    dry_run=dry_run,
                )

            return self._route(
                metrics, score, "idle", "pause_job", context, dry_run, p
            )

        # 3. Nada detectado
        return Decision(
            job_id=metrics.job_id,
            namespace=metrics.namespace,
            route=DecisionRoute.IGNORE,
            score=0.0,
            trigger="none",
            suggested_action="noop",
            context=context,
            dry_run=dry_run,
        )

    def _route(
        self,
        metrics: GPUJobMetrics,
        score: float,
        trigger: str,
        action: str,
        context: dict,
        dry_run: bool,
        p: dict,
    ) -> Decision:
        thr            = p["thresholds"]
        score_auto_act = thr["idle"]["score_auto_act"]
        score_llm      = thr["idle"]["score_llm"]

        if score >= score_auto_act:
            if self._is_circuit_open(p):
                return Decision(
                    job_id=metrics.job_id,
                    namespace=metrics.namespace,
                    route=DecisionRoute.BLOCKED,
                    score=score,
                    trigger=trigger,
                    suggested_action=action,
                    context=context,
                    dry_run=dry_run,
                )
            self._register_action()
            return Decision(
                job_id=metrics.job_id,
                namespace=metrics.namespace,
                route=DecisionRoute.AUTO_ACT,
                score=score,
                trigger=trigger,
                suggested_action=action,
                context=context,
                dry_run=dry_run,
            )

        if score >= score_llm:
            return Decision(
                job_id=metrics.job_id,
                namespace=metrics.namespace,
                route=DecisionRoute.CALL_LLM,
                score=score,
                trigger=trigger,
                suggested_action=action,
                context=context,
                dry_run=dry_run,
            )

        return Decision(
            job_id=metrics.job_id,
            namespace=metrics.namespace,
            route=DecisionRoute.IGNORE,
            score=score,
            trigger=trigger,
            suggested_action="noop",
            context=context,
            dry_run=dry_run,
        )
