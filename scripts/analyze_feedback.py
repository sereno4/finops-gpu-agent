"""
analyze_feedback.py — Feedback loop do agente FinOps GPU.
Le o audit.db e gera relatorio de rejeicoes humanas
e erros de parsing para ajuste do system prompt do LLM.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.audit.trace import AuditStore


def analyze(db_path: str = "audit.db"):
    if not os.path.exists(db_path):
        print(f"Arquivo {db_path} nao encontrado.")
        print("Rode o agente primeiro: python main.py")
        return

    store    = AuditStore(db_path=db_path)
    rejected = store.list_rejected()
    errors   = store.list_parse_errors()

    print()
    print("=" * 60)
    print("RELATORIO DE FEEDBACK LOOP — FinOps GPU Agent")
    print("=" * 60)
    print(f"Decisoes rejeitadas por humanos : {len(rejected)}")
    print(f"Erros de parsing do LLM         : {len(errors)}")
    print()

    if rejected:
        print("── Padroes de rejeicao ──────────────────────────────")
        actions  = Counter(t.action_taken for t in rejected)
        triggers = Counter(t.trigger for t in rejected)
        print(f"Acoes mais rejeitadas  : {dict(actions)}")
        print(f"Triggers mais rejeit.  : {dict(triggers)}")

        print()
        print("Ultimas 5 rejeicoes:")
        for t in rejected[-5:]:
            print(
                f"  [{t.ts[:19]}] {t.job_id} | "
                f"{t.action_taken} | score={t.score:.3f}"
            )
            if t.llm_raw_response:
                try:
                    resp = json.loads(t.llm_raw_response)
                    reason = resp.get("reason", "?")[:80]
                    print(f"    LLM reason: {reason}")
                except Exception:
                    pass
        print()

    if errors:
        print("── Erros de parsing ─────────────────────────────────")
        for t in errors[-3:]:
            print(
                f"  [{t.ts[:19]}] {t.job_id} | "
                f"{t.parse_error[:100]}"
            )
        print()

    print("── Sugestoes para ajuste de prompt ──────────────────")
    sugestoes = 0

    if len(rejected) >= 5:
        print(
            "  5+ rejeicoes — revise os criterios de "
            "'pause_job' no system prompt"
        )
        sugestoes += 1

    if len(errors) >= 3:
        print(
            "  3+ erros de parsing — reforce "
            "'responda APENAS com JSON' no system prompt"
        )
        sugestoes += 1

    if rejected:
        acoes = Counter(t.action_taken for t in rejected)
        mais_rejeitada = acoes.most_common(1)[0][0]
        print(
            f"  Acao mais rejeitada foi '{mais_rejeitada}' — "
            f"revise as regras dessa acao no prompt"
        )
        sugestoes += 1

    if sugestoes == 0:
        print("  Nenhuma rejeicao ou erro — sistema funcionando bem")

    print()

    # Exporta fixture pytest para o trace mais recente rejeitado
    if rejected:
        ultimo = rejected[-1]
        fixture = store.export_as_pytest_fixture(ultimo.request_id)
        fixture_path = "tests/unit/test_replay_latest.py"
        with open(fixture_path, "w") as f:
            f.write(fixture)
        print(f"Fixture de replay gerada em: {fixture_path}")
        print(f"  request_id : {ultimo.request_id}")
        print(f"  job_id     : {ultimo.job_id}")
        print()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "audit.db"
    analyze(db)
