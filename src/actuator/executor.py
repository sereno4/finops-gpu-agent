"""
executor.py — Executa acoes validadas pela camada deterministica.
O LLM NUNCA chama este modulo diretamente.
Toda acao passa por validacao antes de chegar aqui.
dry_run=True: apenas loga, sem executar nada real.
"""
from typing import Optional

from ..engine.policy_engine import Decision, DecisionRoute
from ..llm.contract import LLMAction
from ..llm.advisor import LLMAdvisor, build_prompt
from ..audit.trace import AuditStore, DecisionTrace


class ActionExecutor:

    def __init__(
        self,
        audit_store: AuditStore,
        advisor: Optional[LLMAdvisor] = None,
        slack_webhook: Optional[str] = None,
    ):
        self.audit         = audit_store
        self.advisor       = advisor or LLMAdvisor()
        self.slack_webhook = slack_webhook

    def process(self, decision: Decision) -> DecisionTrace:
        """Ponto de entrada: recebe Decision e age."""
        trace = DecisionTrace(
            job_id=decision.job_id,
            namespace=decision.namespace,
            trigger=decision.trigger,
            score=decision.score,
            context_snapshot=decision.context,
            dry_run=decision.dry_run,
        )

        if decision.route == DecisionRoute.IGNORE:
            trace.decided_by   = "rule"
            trace.action_taken = "noop"
            self.audit.save(trace)
            return trace

        if decision.route == DecisionRoute.BLOCKED:
            trace.decided_by   = "rule"
            trace.action_taken = "blocked_circuit_breaker"
            self._notify(
                f"Circuit breaker ativo — acao bloqueada "
                f"para `{decision.job_id}`"
            )
            self.audit.save(trace)
            return trace

        if decision.route == DecisionRoute.AUTO_ACT:
            trace.decided_by   = "rule"
            trace.action_taken = decision.suggested_action
            self._execute(
                decision.suggested_action,
                decision.job_id,
                decision.dry_run,
            )
            self._notify(
                f"[AUTO] `{decision.suggested_action}` em "
                f"`{decision.job_id}` | score={decision.score} "
                f"| dry_run={decision.dry_run}"
            )
            self.audit.save(trace)
            return trace

        if decision.route == DecisionRoute.CALL_LLM:
            return self._handle_llm(decision, trace)

        return trace

    def _handle_llm(
        self, decision: Decision, trace: DecisionTrace
    ) -> DecisionTrace:
        prompt = build_prompt(decision)
        trace.prompt_rendered = prompt

        llm_action, error = self.advisor.advise(decision)

        if error:
            trace.decided_by       = "rule"
            trace.action_taken     = "escalated_human"
            trace.parse_error      = error
            trace.llm_raw_response = error
            self._notify(
                f"Erro de parsing LLM — escalando para humano\n"
                f"Job: `{decision.job_id}`\n"
                f"Erro: `{error[:200]}`\n"
                f"request_id: `{trace.request_id}`"
            )
            self.audit.save(trace)
            return trace

        trace.decided_by         = "llm"
        trace.llm_raw_response   = llm_action.model_dump_json()
        trace.action_taken       = llm_action.action
        trace.requires_approval  = llm_action.requires_approval
        trace.cost_saved_usd_day = llm_action.estimated_savings_usd_day or 0.0

        if llm_action.requires_approval:
            self._notify(
                f"Aprovacao necessaria\n"
                f"Job: `{decision.job_id}` | "
                f"Acao: `{llm_action.action}`\n"
                f"Motivo: {llm_action.reason}\n"
                f"Economia: USD {llm_action.estimated_savings_usd_day:.2f}/dia\n"
                f"request_id: `{trace.request_id}`"
            )
        else:
            self._execute(
                llm_action.action,
                decision.job_id,
                decision.dry_run,
            )
            self._notify(
                f"[LLM] `{llm_action.action}` em `{decision.job_id}` "
                f"| confidence={llm_action.confidence} "
                f"| {llm_action.reason}"
            )

        self.audit.save(trace)
        return trace

    def _execute(self, action: str, job_id: str, dry_run: bool):
        if dry_run:
            print(f"[DRY-RUN] {action} -> {job_id}")
            return

        if action == "pause_job":
            print(f"[EXEC] kubectl annotate pod {job_id} finops/paused=true")
        elif action == "scale_down":
            print(f"[EXEC] kubectl scale deployment {job_id} --replicas=0")
        elif action == "recommend":
            pass
        else:
            print(f"[EXEC] noop -> {job_id}")

    def _notify(self, message: str):
        if not self.slack_webhook:
            print(f"[SLACK] {message}")
            return
        try:
            import httpx
            httpx.post(
                self.slack_webhook,
                json={"text": message},
                timeout=5,
            )
        except Exception as e:
            print(f"[SLACK ERROR] {e}: {message}")
