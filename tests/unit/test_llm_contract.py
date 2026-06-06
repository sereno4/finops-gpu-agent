"""
test_llm_contract.py
Valida o schema Pydantic do contrato LLM.
Cada teste de falha representa uma alucinacao real
que o LLM pode produzir em producao.
"""
import json
import pytest
from pydantic import ValidationError
from src.llm.contract import LLMAction


class TestLLMActionValid:

    def test_pause_job_minimo(self):
        raw = json.dumps({
            "action": "pause_job",
            "target": "job-train-resnet",
            "reason": "GPU ociosa ha 95 minutos com utilizacao de 4%",
            "confidence": 0.92,
            "requires_approval": False,
        })
        action = LLMAction.model_validate_json(raw)
        assert action.action == "pause_job"
        assert action.confidence == 0.92

    def test_recommend_com_economia(self):
        raw = json.dumps({
            "action": "recommend",
            "target": "job-batch-embeddings",
            "reason": "Utilizacao borderline, recomendo revisar batch size antes de pausar",
            "confidence": 0.65,
            "requires_approval": True,
            "estimated_savings_usd_day": 18.50,
            "recommendation_text": "Considere reduzir gpu_count de 4 para 2",
        })
        action = LLMAction.model_validate_json(raw)
        assert action.requires_approval is True
        assert action.estimated_savings_usd_day == 18.50

    def test_noop_valido(self):
        raw = json.dumps({
            "action": "noop",
            "target": "job-inference-api",
            "reason": "Job funcionando normalmente, sem intervencao necessaria",
            "confidence": 0.98,
        })
        action = LLMAction.model_validate_json(raw)
        assert action.action == "noop"

    def test_confidence_arredondado(self):
        raw = json.dumps({
            "action": "recommend",
            "target": "job-x",
            "reason": "Situacao ambigua que requer revisao manual do operador",
            "confidence": 0.777777,
        })
        action = LLMAction.model_validate_json(raw)
        assert action.confidence == 0.778


class TestLLMActionInvalid:

    def test_acao_invalida(self):
        """LLM inventou uma acao que nao existe no contrato"""
        raw = json.dumps({
            "action": "delete_cluster",
            "target": "job-x",
            "reason": "Acao que nao existe no contrato do agente",
            "confidence": 0.9,
        })
        with pytest.raises(ValidationError):
            LLMAction.model_validate_json(raw)

    def test_confidence_acima_de_1(self):
        """LLM retornou confidence fora do range"""
        raw = json.dumps({
            "action": "noop",
            "target": "job-x",
            "reason": "Confianca fora do intervalo valido permitido",
            "confidence": 1.5,
        })
        with pytest.raises(ValidationError):
            LLMAction.model_validate_json(raw)

    def test_reason_muito_curto(self):
        """LLM retornou reason abaixo do minimo — forcamos justificativa"""
        raw = json.dumps({
            "action": "noop",
            "target": "job-x",
            "reason": "ok",
            "confidence": 0.5,
        })
        with pytest.raises(ValidationError):
            LLMAction.model_validate_json(raw)

    def test_target_vazio(self):
        """LLM retornou target vazio — nao podemos agir sem saber o alvo"""
        raw = json.dumps({
            "action": "pause_job",
            "target": "",
            "reason": "Target vazio nao e permitido pelo contrato",
            "confidence": 0.8,
        })
        with pytest.raises(ValidationError):
            LLMAction.model_validate_json(raw)

    def test_json_malformado(self):
        """LLM retornou texto que nao e JSON valido"""
        with pytest.raises(Exception):
            LLMAction.model_validate_json("{ action: pause_job }")

    def test_markdown_fence_rejeitado(self):
        """LLM embrulhou o JSON em ```json``` — deve ser tratado antes"""
        raw = '```json\n{"action":"noop","target":"x","reason":"markdown fence problem","confidence":0.5}\n```'
        with pytest.raises(Exception):
            LLMAction.model_validate_json(raw)
