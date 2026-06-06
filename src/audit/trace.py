"""
trace.py — Rastreabilidade completa de cada decisao.
Salva: quem decidiu (regra/LLM/humano), prompt exato,
resposta bruta, acao tomada, custo economizado.
Permite replay em pytest para debugar comportamento do LLM.
"""
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional


@dataclass
class DecisionTrace:
    request_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    job_id: str = ""
    namespace: str = ""
    decided_by: Literal["rule", "llm", "human"] = "rule"
    trigger: str = ""
    score: float = 0.0
    context_snapshot: dict = field(default_factory=dict)
    prompt_rendered: str = ""        # prompt exato enviado ao LLM
    llm_raw_response: str = ""       # resposta bruta para replay
    action_taken: str = "noop"
    dry_run: bool = True
    requires_approval: bool = False
    human_verdict: Optional[
        Literal["approved", "rejected", "modified"]
    ] = None
    cost_saved_usd_day: float = 0.0
    parse_error: Optional[str] = None
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AuditStore:
    """
    Persiste DecisionTrace em SQLite (dev) ou Postgres (prod).
    Suporta replay: exporta trace como fixture pytest.
    """

    def __init__(self, db_path: str = "audit.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decision_traces (
                    request_id        TEXT PRIMARY KEY,
                    job_id            TEXT,
                    namespace         TEXT,
                    decided_by        TEXT,
                    trigger           TEXT,
                    score             REAL,
                    context_snapshot  TEXT,
                    prompt_rendered   TEXT,
                    llm_raw_response  TEXT,
                    action_taken      TEXT,
                    dry_run           INTEGER,
                    requires_approval INTEGER,
                    human_verdict     TEXT,
                    cost_saved_usd_day REAL,
                    parse_error       TEXT,
                    ts                TEXT
                )
            """)

    def save(self, trace: DecisionTrace):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO decision_traces VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    trace.request_id,
                    trace.job_id,
                    trace.namespace,
                    trace.decided_by,
                    trace.trigger,
                    trace.score,
                    json.dumps(trace.context_snapshot),
                    trace.prompt_rendered,
                    trace.llm_raw_response,
                    trace.action_taken,
                    int(trace.dry_run),
                    int(trace.requires_approval),
                    trace.human_verdict,
                    trace.cost_saved_usd_day,
                    trace.parse_error,
                    trace.ts,
                ),
            )

    def get(self, request_id: str) -> Optional[DecisionTrace]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM decision_traces WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_trace(row)

    def list_parse_errors(self) -> list:
        """Traces com erro de parsing — para ajuste de prompt."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM decision_traces "
                "WHERE parse_error IS NOT NULL"
            ).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def list_rejected(self) -> list:
        """Decisoes rejeitadas por humanos — feedback loop."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM decision_traces "
                "WHERE human_verdict = 'rejected'"
            ).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def export_as_pytest_fixture(self, request_id: str) -> str:
        """
        Gera codigo Python pronto para colar em um teste.
        Reproduz exatamente o cenario que gerou comportamento estranho.
        """
        trace = self.get(request_id)
        if not trace:
            return f"# trace {request_id} nao encontrado"

        short = trace.request_id.replace("-", "_")[:8]
        return f'''# fixture gerada automaticamente — request_id: {trace.request_id}
# job: {trace.job_id} | trigger: {trace.trigger} | score: {trace.score}
import pytest
from src.llm.contract import LLMAction

CONTEXT = {json.dumps(trace.context_snapshot, indent=4)}
PROMPT_RENDERED = """{trace.prompt_rendered}"""
LLM_RAW_RESPONSE = """{trace.llm_raw_response}"""

def test_replay_{short}():
    """Replay do trace {trace.request_id}"""
    action = LLMAction.model_validate_json(LLM_RAW_RESPONSE)
    assert action.action in ["pause_job", "scale_down", "recommend", "noop"]
    assert 0.0 <= action.confidence <= 1.0
'''

    def _row_to_trace(self, row) -> DecisionTrace:
        return DecisionTrace(
            request_id=row[0],
            job_id=row[1],
            namespace=row[2],
            decided_by=row[3],
            trigger=row[4],
            score=row[5],
            context_snapshot=json.loads(row[6]),
            prompt_rendered=row[7],
            llm_raw_response=row[8],
            action_taken=row[9],
            dry_run=bool(row[10]),
            requires_approval=bool(row[11]),
            human_verdict=row[12],
            cost_saved_usd_day=row[13],
            parse_error=row[14],
            ts=row[15],
        )
