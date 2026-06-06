"""
test_audit_trace.py
Valida persistencia, recuperacao, feedback loop
e export de fixture pytest do AuditStore.
"""
import pytest
from src.audit.trace import AuditStore, DecisionTrace


@pytest.fixture
def store(tmp_path):
    return AuditStore(db_path=str(tmp_path / "test.db"))


def make_trace(**kwargs) -> DecisionTrace:
    defaults = dict(
        job_id="job-test",
        namespace="ml-research",
        decided_by="rule",
        trigger="idle",
        score=0.91,
        context_snapshot={"util_pct": 3.0, "duration_minutes": 90},
        prompt_rendered="Prompt de teste para o job",
        llm_raw_response=(
            '{"action":"pause_job","target":"job-test",'
            '"reason":"GPU muito ociosa ha 90 minutos","confidence":0.91}'
        ),
        action_taken="pause_job",
        dry_run=True,
    )
    defaults.update(kwargs)
    return DecisionTrace(**defaults)


class TestAuditStore:

    def test_salvar_e_recuperar(self, store):
        trace = make_trace()
        store.save(trace)
        recovered = store.get(trace.request_id)
        assert recovered is not None
        assert recovered.job_id == "job-test"
        assert recovered.score == 0.91

    def test_context_snapshot_preservado(self, store):
        trace = make_trace()
        store.save(trace)
        recovered = store.get(trace.request_id)
        assert recovered.context_snapshot["util_pct"] == 3.0
        assert recovered.context_snapshot["duration_minutes"] == 90

    def test_id_inexistente_retorna_none(self, store):
        result = store.get("uuid-que-nao-existe")
        assert result is None

    def test_listar_erros_de_parsing(self, store):
        bom   = make_trace()
        erro  = make_trace(parse_error="PARSE_ERROR: campo action invalido")
        store.save(bom)
        store.save(erro)
        erros = store.list_parse_errors()
        assert len(erros) == 1
        assert erros[0].parse_error is not None

    def test_listar_rejeitados_feedback_loop(self, store):
        aprovado  = make_trace(human_verdict="approved")
        rejeitado = make_trace(human_verdict="rejected")
        ignorado  = make_trace()
        for t in [aprovado, rejeitado, ignorado]:
            store.save(t)
        rejeitados = store.list_rejected()
        assert len(rejeitados) == 1
        assert rejeitados[0].human_verdict == "rejected"

    def test_export_pytest_fixture(self, store):
        trace = make_trace(decided_by="llm")
        store.save(trace)
        code = store.export_as_pytest_fixture(trace.request_id)
        assert "def test_replay_" in code
        assert trace.request_id[:8] in code
        assert "LLMAction.model_validate_json" in code

    def test_export_id_invalido(self, store):
        code = store.export_as_pytest_fixture("id-invalido")
        assert "nao encontrado" in code

    def test_sobrescrever_mesmo_request_id(self, store):
        trace = make_trace()
        store.save(trace)
        trace.action_taken = "noop"
        store.save(trace)
        recovered = store.get(trace.request_id)
        assert recovered.action_taken == "noop"
