"""
contract.py — Schema Pydantic da resposta do LLM.
Documenta o contrato e valida antes de qualquer acao.
Falha de parsing -> nunca quebra o engine,
sempre cai no fallback de human-in-the-loop.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class LLMAction(BaseModel):
    action: Literal["pause_job", "scale_down", "recommend", "noop"]
    target: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(..., min_length=10, max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)
    requires_approval: bool = False
    estimated_savings_usd_day: Optional[float] = Field(None, ge=0.0)
    recommendation_text: Optional[str] = Field(None, max_length=1000)

    @field_validator("confidence")
    @classmethod
    def confidence_precision(cls, v: float) -> float:
        return round(v, 3)
