"""
test_full_pipeline.py
Teste de integracao end-to-end.
MockBackend -> PolicyEngine -> ActionExecutor (dry_run=True).
LLMAdvisor mockado — sem GPU, sem cloud, sem API key.
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from src.collector.mock_backend import MockBackend
from src.collector.base import GPUJobMetrics
from src.engine.policy_engine import PolicyEngine, DecisionRoute
from src.actuator.executor import ActionExecutor
from src.audit.trace import AuditStore
from src.llm.advisor import LLMAdvisor
from src.llm.contract import LLMAction


def make_job(**kwargs) -> GPUJobMetrics:
    defaults = dict(
        job_id="job-test",
        namespace="ml-research",
        gpu_type="mock",
        util_pct=50.0,
        vram_pct=50.0,
        duration_minutes=60,
        gpu_count=1,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    defaults.update(kwargs)
    return GPUJobMetrics(**defaults)


@pytest.fixture
def engine(tmp_path):
    p = tmp_path / "policies.yaml"
    p.write_text("""
global:
  dry_run: true
  circuit_breaker:
    max_actions_per_hour: 20
    cooldown_minutes: 15
thresholds:
  idle:
    util_pct_below: 15
    duration_minutes: 30
    score_auto_act: 0.85
    score_llm: 0.50
  vram_anomaly:
    util_pct_above: 95
    duration_minutes: 10
  cost_alert_usd_per_hour: 2.50
gpu_cost:
  usd_per_hour:
    default: 1.00
    mock: 1.00
    a100: 4.10
    v100: 2.48
    t4: 0.68
teams:
  - name: ml-research
    namespace: ml-research
    allow_auto_pause: true
    notify_slack: "#test"
  - name: data-eng
    namespace: data-engineering
    allow_auto_pause: false
    notify_slack: "#test"
  - name: platform
    namespace: platform
    allow_auto_pause: true
    notify_slack: "#test"
actions:
  pause_job:
    requires_approval_above_cost_usd: 50
    max_per_hour: 5
  scale_down:
    requires_approval: true
  recommend:
    requires_approval: false
  noop:
    requires_approval: false
""")
    return PolicyEngine(policies_path=str(p))


@pytest.fixture
def store(tmp_path):
    return AuditStore(db_path=str(tmp_path / "test.db"))


class TestFullPipeline:

    def test_pipeline_roda_sem_erro(self, engine, store):
        """Todos os cenarios do scenarios.yaml sem nenhuma excecao"""
        backend  = MockBackend(scenarios_path="config/scenarios.yaml")
        executor = ActionExecutor(audit_store=store)

        for m in backend.collect():
            decision = engine.evaluate(m)
            trace    = executor.process(decision)
            assert trace is not None
            assert trace.action_taken is not None

    def test_job_muito_idle_vira_auto_act(self, engine, store):
        """util=2%, 210min, ml-research -> AUTO_ACT -> pause_job"""
        m = make_job(
            job_id="job-experiment-42",
            namespace="ml-research",
            gpu_type="t4",
            util_pct=2.0,
            duration_minutes=210,
        )
        decision = engine.evaluate(m)
        assert decision.route == DecisionRoute.AUTO_ACT

        executor = ActionExecutor(audit_store=store)
        trace    = executor.process(decision)

        assert trace.action_taken == "pause_job"
        assert trace.decided_by   == "rule"
        assert trace.dry_run      is True

        recovered = store.get(trace.request_id)
        assert recovered is not None

    def test_job_moderado_vai_para_llm(self, engine, store):
        """util=4%, 95min -> score medio -> CALL_LLM"""
        m = make_job(
            job_id="job-train-resnet",
            namespace="ml-research",
            util_pct=4.0,
            duration_minutes=95,
        )
        decision = engine.evaluate(m)
        assert decision.route == DecisionRoute.CALL_LLM

    def test_erro_parsing_llm_escala_para_humano(self, engine, store):
        """LLM retorna JSON invalido -> escalado para humano"""
        m = make_job(
            job_id="job-borderline",
            namespace="data-engineering",
            gpu_type="v100",
            util_pct=5.0,
            duration_minutes=100,
        )
        decision = engine.evaluate(m)
        assert decision.route == DecisionRoute.CALL_LLM

        advisor_mock = MagicMock(spec=LLMAdvisor)
        advisor_mock.advise.return_value = (
            None, "PARSE_ERROR: campo action invalido"
        )

        executor = ActionExecutor(audit_store=store, advisor=advisor_mock)
        trace    = executor.process(decision)

        assert trace.action_taken == "escalated_human"
        assert trace.parse_error  is not None
        assert "PARSE_ERROR"      in trace.parse_error

        recovered = store.get(trace.request_id)
        assert recovered.parse_error is not None

    def test_llm_valido_executa_e_salva(self, engine, store):
        """LLM retorna JSON valido -> executa e salva decided_by=llm"""
        m = make_job(
            job_id="job-borderline-2",
            namespace="data-engineering",
            gpu_type="v100",
            util_pct=5.0,
            duration_minutes=100,
        )
        decision = engine.evaluate(m)

        action_valida = LLMAction(
            action="recommend",
            target="job-borderline-2",
            reason="Utilizacao baixa, recomendo revisar configuracao do job",
            confidence=0.78,
            requires_approval=False,
            estimated_savings_usd_day=12.0,
        )
        advisor_mock = MagicMock(spec=LLMAdvisor)
        advisor_mock.advise.return_value = (action_valida, None)

        executor = ActionExecutor(audit_store=store, advisor=advisor_mock)
        trace    = executor.process(decision)

        assert trace.decided_by          == "llm"
        assert trace.action_taken        == "recommend"
        assert trace.cost_saved_usd_day  == 12.0

    def test_todos_jobs_tem_trace_no_audit(self, engine, store):
        """Todo job processado deve ter trace salvo no AuditStore"""
        backend      = MockBackend(scenarios_path="config/scenarios.yaml")
        advisor_mock = MagicMock(spec=LLMAdvisor)
        advisor_mock.advise.return_value = (None, "sem api key")

        executor = ActionExecutor(audit_store=store, advisor=advisor_mock)

        for m in backend.collect():
            decision  = engine.evaluate(m)
            trace     = executor.process(decision)
            recovered = store.get(trace.request_id)
            assert recovered is not None, (
                f"Trace nao encontrado para {m.job_id}"
            )
