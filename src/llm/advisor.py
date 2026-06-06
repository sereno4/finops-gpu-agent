"""
advisor.py — Camada LLM.
Chamada apenas quando PolicyEngine decide CALL_LLM.
Retorna (LLMAction, None) em sucesso.
Retorna (None, mensagem_erro) em qualquer falha —
o executor faz fallback para human-in-the-loop.
"""
import os
from typing import Optional

import httpx
from pydantic import ValidationError

from ..engine.policy_engine import Decision
from .contract import LLMAction


SYSTEM_PROMPT = """Voce e um agente FinOps especializado em otimizacao de custos de GPU.

Recebe metricas de um job GPU e deve retornar SOMENTE um JSON valido:
{
  "action": "pause_job" | "scale_down" | "recommend" | "noop",
  "target": "<job_id>",
  "reason": "<explicacao clara em portugues, minimo 10 caracteres>",
  "confidence": <0.0 a 1.0>,
  "requires_approval": true | false,
  "estimated_savings_usd_day": <numero ou null>,
  "recommendation_text": "<texto para o time, opcional>"
}

Regras:
- "pause_job": util < 10% por mais de 1h e confidence >= 0.8
- "scale_down": gpu_count > 1 e util_pct < 30%
- "recommend": situacoes ambiguas ou quando requer aprovacao
- "noop": sem problema claro identificado
- requires_approval = true se estimated_savings_usd_day > 20
- Responda APENAS com o JSON, sem markdown, sem texto fora do JSON
"""


def build_prompt(decision: Decision) -> str:
    ctx = decision.context
    return f"""Job ID: {decision.job_id}
Namespace: {decision.namespace}
Trigger detectado: {decision.trigger}
Score determinístico: {decision.score}

Metricas atuais:
- Utilizacao GPU : {ctx['util_pct']}%
- Utilizacao VRAM: {ctx['vram_pct']}%
- Duracao do job : {ctx['duration_minutes']} minutos
- Numero de GPUs : {ctx['gpu_count']}
- Tipo de GPU    : {ctx['gpu_type']}
- Custo atual    : USD {ctx['cost_usd_per_hour']:.2f}/hora

Acao sugerida pela camada deterministica: {decision.suggested_action}

Analise e retorne o JSON de decisao."""


class LLMAdvisor:

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model   = "claude-sonnet-4-20250514"

    def advise(
        self, decision: Decision
    ) -> tuple[Optional[LLMAction], Optional[str]]:
        """
        Retorna (LLMAction, None) em sucesso.
        Retorna (None, erro) em falha — nunca levanta excecao.
        """
        if not self.api_key:
            return None, "ANTHROPIC_API_KEY nao configurada"

        prompt = build_prompt(decision)
        raw    = ""

        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      self.model,
                    "max_tokens": 512,
                    "system":     SYSTEM_PROMPT,
                    "messages":   [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()

            # Remove markdown fence se o modelo incluir por engano
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            action = LLMAction.model_validate_json(raw)
            return action, None

        except ValidationError as e:
            return None, f"PARSE_ERROR: {e} | raw: {raw}"
        except Exception as e:
            return None, f"API_ERROR: {e}"
