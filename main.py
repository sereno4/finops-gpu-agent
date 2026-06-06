"""
main.py — Loop principal do agente FinOps GPU.
Coleta metricas -> PolicyEngine -> ActionExecutor.
Controle por variaveis de ambiente — zero mudanca de codigo
entre dev (mock) e producao (prometheus).
"""
import os
import time

from src.collector.mock_backend import MockBackend
from src.collector.prometheus_backend import PrometheusBackend
from src.engine.policy_engine import PolicyEngine
from src.actuator.executor import ActionExecutor
from src.audit.trace import AuditStore


def build_collector():
    backend = os.getenv("METRICS_BACKEND", "mock")
    if backend == "prometheus":
        url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
        return PrometheusBackend(prometheus_url=url)
    return MockBackend(scenarios_path="config/scenarios.yaml")


def main():
    collector = build_collector()
    engine    = PolicyEngine(policies_path="config/policies.yaml")
    audit     = AuditStore(db_path="audit.db")
    executor  = ActionExecutor(
        audit_store=audit,
        slack_webhook=os.getenv("SLACK_WEBHOOK"),
    )

    backend  = os.getenv("METRICS_BACKEND", "mock")
    interval = int(os.getenv("EVAL_INTERVAL_SECONDS", "60"))

    print(f"Agente FinOps GPU iniciado")
    print(f"  backend  : {backend}")
    print(f"  interval : {interval}s")
    print(f"  dry_run  : verificar config/policies.yaml")
    print()

    while True:
        metrics_list = collector.collect()
        print(f"[{len(metrics_list)} jobs avaliados]")

        for m in metrics_list:
            decision = engine.evaluate(m)
            trace    = executor.process(decision)
            print(
                f"  {m.job_id:30s} | "
                f"route={decision.route.value:10s} | "
                f"score={decision.score:.3f} | "
                f"action={trace.action_taken}"
            )

        print()
        time.sleep(interval)


if __name__ == "__main__":
    main()
EOFcat > main.py << 'EOF'
"""
main.py — Loop principal do agente FinOps GPU.
Coleta metricas -> PolicyEngine -> ActionExecutor.
Controle por variaveis de ambiente — zero mudanca de codigo
entre dev (mock) e producao (prometheus).
"""
import os
import time

from src.collector.mock_backend import MockBackend
from src.collector.prometheus_backend import PrometheusBackend
from src.engine.policy_engine import PolicyEngine
from src.actuator.executor import ActionExecutor
from src.audit.trace import AuditStore


def build_collector():
    backend = os.getenv("METRICS_BACKEND", "mock")
    if backend == "prometheus":
        url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
        return PrometheusBackend(prometheus_url=url)
    return MockBackend(scenarios_path="config/scenarios.yaml")


def main():
    collector = build_collector()
    engine    = PolicyEngine(policies_path="config/policies.yaml")
    audit     = AuditStore(db_path="audit.db")
    executor  = ActionExecutor(
        audit_store=audit,
        slack_webhook=os.getenv("SLACK_WEBHOOK"),
    )

    backend  = os.getenv("METRICS_BACKEND", "mock")
    interval = int(os.getenv("EVAL_INTERVAL_SECONDS", "60"))

    print(f"Agente FinOps GPU iniciado")
    print(f"  backend  : {backend}")
    print(f"  interval : {interval}s")
    print(f"  dry_run  : verificar config/policies.yaml")
    print()

    while True:
        metrics_list = collector.collect()
        print(f"[{len(metrics_list)} jobs avaliados]")

        for m in metrics_list:
            decision = engine.evaluate(m)
            trace    = executor.process(decision)
            print(
                f"  {m.job_id:30s} | "
                f"route={decision.route.value:10s} | "
                f"score={decision.score:.3f} | "
                f"action={trace.action_taken}"
            )

        print()
        time.sleep(interval)


if __name__ == "__main__":
    main()
