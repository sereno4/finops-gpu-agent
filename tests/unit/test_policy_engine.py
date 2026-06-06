"""
test_policy_engine.py
Valida a camada deterministica: scores, rotas,
circuit breaker e politica por equipe.
Zero dependencia de LLM ou cloud.
"""
import pytest
from datetime import datetime, timezone
from src.engine.policy_engine import (
    PolicyEngine, DecisionRoute, idle_score, vram_score
)
from src.collector.base import GPUJobMetrics


def make_metrics(**kwargs) -> GPUJobMetrics:
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
    max_actions_per_hour: 10
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
teams:
  - name: ml-research
    namespace: ml-research
    allow_auto_pause: true
    notify_slack: "#test"
  - name: data-eng
    namespace: data-engineering
    allow_auto_pause: false
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


# ── scores ────────────────────────────────────────────────────

class TestIdleScore:

    def test_muito_idle_por_muito_tempo(self):
        """util=2%, 210min -> score alto -> AUTO_ACT"""
        score = idle_score(2.0, 210)
        assert score >= 0.85

    def test_idle_moderado(self):
        """util=4%, 95min -> score medio -> CALL_LLM"""
        score = idle_score(4.0, 95)
        assert 0.50 <= score < 0.85

    def test_borderline_ignorado(self):
        """util=13%, 38min -> score baixo -> IGNORE"""
        score = idle_score(13.0, 38)
        assert score < 0.50

    def test_no_threshold_so_persistencia(self):
        """util=15% -> intensidade zero, so persistencia contribui"""
        score = idle_score(15.0, 120)
        assert score == 0.4

    def test_score_sempre_entre_0_e_1(self):
        for util in [0, 5, 10, 14.9]:
            for dur in [30, 60, 120, 300]:
                s = idle_score(util, dur)
                assert 0.0 <= s <= 1.0, (
                    f"Score fora do intervalo: util={util}, dur={dur}, score={s}"
                )


class TestVramScore:

    def test_vram_critica(self):
        """VRAM 99%, 20min -> score positivo"""
        score = vram_score(99.0, 20)
        assert score > 0.0

    def test_vram_normal_nao_aciona(self):
        """VRAM 80% -> abaixo do threshold de 95%, nao deve acionar LLM"""
        score = vram_score(80.0, 60)
        assert score < 0.50


# ── roteamento ────────────────────────────────────────────────

class TestPolicyEngineRouting:

    def test_muito_idle_vira_auto_act(self, engine):
        """util=2%, 210min, ml-research -> AUTO_ACT"""
        m = make_metrics(util_pct=2.0, duration_minutes=210)
        d = engine.evaluate(m)
        assert d.route == DecisionRoute.AUTO_ACT
        assert d.trigger == "idle"
        assert d.suggested_action == "pause_job"

    def test_idle_moderado_vai_para_llm(self, engine):
        """util=4%, 95min -> score medio -> CALL_LLM"""
        m = make_metrics(util_pct=4.0, duration_minutes=95)
        d = engine.evaluate(m)
        assert d.route == DecisionRoute.CALL_LLM

    def test_borderline_ignorado(self, engine):
        """util=14%, 32min -> score baixo -> IGNORE"""
        m = make_metrics(util_pct=14.0, duration_minutes=32)
        d = engine.evaluate(m)
        assert d.route == DecisionRoute.IGNORE

    def test_job_saudavel_ignorado(self, engine):
        """util=75% -> IGNORE"""
        m = make_metrics(util_pct=75.0, duration_minutes=120)
        d = engine.evaluate(m)
        assert d.route == DecisionRoute.IGNORE

    def test_equipe_sem_autopause_vai_para_llm(self, engine):
        """data-engineering nao permite auto-pause
        mesmo com score alto vai para CALL_LLM"""
        m = make_metrics(
            util_pct=1.0,
            duration_minutes=200,
            namespace="data-engineering",
        )
        d = engine.evaluate(m)
        assert d.route == DecisionRoute.CALL_LLM

    def test_vram_anomalia_detectada(self, engine):
        """VRAM 98%, 15min -> trigger vram_anomaly"""
        m = make_metrics(vram_pct=98.0, duration_minutes=15, util_pct=90.0)
        d = engine.evaluate(m)
        assert d.trigger == "vram_anomaly"

    def test_circuit_breaker_bloqueia_apos_limite(self, engine):
        """Apos 10 acoes na mesma hora -> BLOCKED"""
        for _ in range(10):
            engine._register_action()
        m = make_metrics(util_pct=1.0, duration_minutes=200)
        d = engine.evaluate(m)
        assert d.route == DecisionRoute.BLOCKED

    def test_dry_run_propagado(self, engine):
        """dry_run do policies.yaml deve chegar na Decision"""
        m = make_metrics(util_pct=2.0, duration_minutes=210)
        d = engine.evaluate(m)
        assert d.dry_run is True

    def test_custo_presente_no_contexto(self, engine):
        """custo/hora deve aparecer no contexto da decisao"""
        m = make_metrics(gpu_type="mock", gpu_count=2)
        d = engine.evaluate(m)
        assert "cost_usd_per_hour" in d.context
        assert d.context["cost_usd_per_hour"] == 2.0
