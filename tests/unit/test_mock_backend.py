"""
test_mock_backend.py
Valida que o MockBackend le o scenarios.yaml corretamente
e que os cenarios cobrem todos os caminhos do PolicyEngine.
"""
import pytest
from src.collector.mock_backend import MockBackend
from src.collector.base import GPUJobMetrics


@pytest.fixture
def backend():
    return MockBackend(scenarios_path="config/scenarios.yaml")


class TestMockBackend:

    def test_retorna_lista_nao_vazia(self, backend):
        result = backend.collect()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_todos_itens_sao_gpu_job_metrics(self, backend):
        for item in backend.collect():
            assert isinstance(item, GPUJobMetrics)

    def test_campos_obrigatorios_presentes(self, backend):
        for m in backend.collect():
            assert m.job_id
            assert m.namespace
            assert m.gpu_type
            assert 0.0 <= m.util_pct <= 100.0
            assert 0.0 <= m.vram_pct <= 100.0
            assert m.duration_minutes >= 0
            assert m.gpu_count >= 1
            assert m.timestamp

    def test_job_idle_presente(self, backend):
        """job-train-resnet deve ter util baixa — cenario idle"""
        jobs = {m.job_id: m for m in backend.collect()}
        assert "job-train-resnet" in jobs
        assert jobs["job-train-resnet"].util_pct < 15.0

    def test_job_saudavel_presente(self, backend):
        """job-inference-api deve ter util alta — cenario saudavel"""
        jobs = {m.job_id: m for m in backend.collect()}
        assert "job-inference-api" in jobs
        assert jobs["job-inference-api"].util_pct > 50.0

    def test_job_vram_anomalia_presente(self, backend):
        """job-finetune-llm deve ter VRAM critica — cenario anomalia"""
        jobs = {m.job_id: m for m in backend.collect()}
        assert "job-finetune-llm" in jobs
        assert jobs["job-finetune-llm"].vram_pct > 95.0
