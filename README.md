Agente de otimização de custos de GPU com camada determinística + LLM.
Detecta GPUs ociosas, consumo anômalo e age automaticamente —
sem delegar decisões críticas ao LLM.

---

## O problema

GPU idle é um dos maiores drenos de budget em infraestrutura de ML.
Em ambientes com múltiplos times e centenas de jobs, é comum ter
30-40% do spend desperdiçado em recursos que ninguém está usando.

Soluções baseadas só em alertas não resolvem — geram fadiga.
Soluções baseadas só em LLM são arriscadas — alucinação pode pausar
um job crítico ou ignorar um problema real.

Este agente resolve com uma arquitetura de duas camadas:
a camada determinística age quando tem certeza,
o LLM só é chamado quando o contexto é ambíguo.

---

## Arquitetura
Métricas (MockBackend / PrometheusBackend)
↓
PolicyEngine  ← policies.yaml (hot reload)
├── score >= 0.85  →  AUTO_ACT   →  ActionExecutor
├── score 0.50–0.84 →  CALL_LLM  →  LLMAdvisor → Pydantic → ActionExecutor
├── circuit breaker →  BLOCKED   →  Slack
└── score < 0.50   →  IGNORE
↓
AuditStore (SQLite / Postgres)
toda decisão salva com prompt + resposta bruta + request_id

**Princípio central:** o LLM nunca executa ação diretamente.
Ele retorna JSON estruturado → Pydantic valida → camada determinística decide se age.
Erro de parsing do LLM → escala para human-in-the-loop no Slack, nunca quebra o engine.

---

## Decisões de design

**Por que separar camada determinística do LLM?**

Latência, custo de token e risco de alucinação tornam o LLM inadequado
para decisões de threshold claro. Um job a 2% de utilização por 4 horas
não precisa de LLM para ser pausado — precisa de uma regra.
O LLM entra onde regra fixa falha: contexto histórico, semântica do job,
recomendações em linguagem natural para o time.

**Por que Pydantic no contrato do LLM?**

O schema Pydantic é documentação viva do que o LLM pode retornar.
Qualquer dev lê `LLMAction` e sabe o contrato sem precisar ler o prompt.
Falha de validação → fallback para humano, nunca exceção silenciosa.

**Por que policy-as-code em YAML?**

Mudar um threshold de 15% para 20% é uma decisão de negócio,
não uma mudança de código. Com `policies.yaml` lido em runtime,
o time de infra abre um PR sem tocar no Python e sem redeployar.
O engine faz hot reload se o arquivo mudar.

**Por que score em vez de threshold binário?**

Um job a 14% por 31 minutos não tem o mesmo peso que um a 3% por 4 horas.
O `idle_score` combina intensidade (quão ociosa) com persistência (por quanto tempo),
produzindo um valor contínuo que alimenta três rotas diferentes em vez de
uma decisão binária que ignora o contexto.

**Por que rastreabilidade completa?**

Sem o prompt exato e a resposta bruta salvos por `request_id`,
debugar comportamento estranho do LLM é arqueologia.
Com `AuditStore.export_as_pytest_fixture(request_id)` você transforma
qualquer decisão real em teste reproduzível em segundos.

**Por que MockBackend que alimenta Prometheus real?**

O `MetricsCollector` sempre fala PromQL — nunca sabe se está em dev ou prod.
O `GPUMockPrometheusCollector` injeta os cenários do YAML no Prometheus local
via Docker Compose. Se a query funciona em dev, funciona em produção com DCGM real.
Elimina uma classe inteira de bugs de integração de ambiente.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Coleta de métricas | DCGM Exporter / prometheus-client (mock) |
| Observabilidade | Prometheus + Grafana |
| Camada determinística | Python puro + PyYAML |
| Contrato LLM | Pydantic v2 |
| LLM | Claude API (Anthropic) |
| Auditoria | SQLite (dev) / Postgres (prod) |
| Notificações | Slack Webhook |
| Orquestração local | Docker Compose |
| Testes | pytest + pytest-cov |

---

## Estrutura do projeto
finops-gpu-agent/
├── main.py                          # loop principal
├── config/
│   ├── policies.yaml                # regras determinísticas (hot reload)
│   └── scenarios.yaml               # dados simulados (5 cenários)
├── src/
│   ├── collector/
│   │   ├── base.py                  # interface GPUJobMetrics
│   │   ├── mock_backend.py          # YAML direto + Custom Collector Prometheus
│   │   └── prometheus_backend.py    # produção via PromQL
│   ├── engine/
│   │   └── policy_engine.py         # idle_score, vram_score, circuit breaker
│   ├── llm/
│   │   ├── contract.py              # schema Pydantic da resposta LLM
│   │   └── advisor.py               # chama Claude API, valida resposta
│   ├── actuator/
│   │   └── executor.py              # dry_run ou real, nunca chamado pelo LLM
│   └── audit/
│       └── trace.py                 # SQLite, export fixture pytest, feedback loop
├── tests/
│   ├── unit/                        # scores, contrato, MockBackend, AuditStore
│   └── integration/                 # pipeline completo com LLM mockado
├── infra/prometheus/                # docker-compose + prometheus.yml
└── scripts/
└── analyze_feedback.py          # relatório de rejeições para ajuste de prompt

---

## Início rápido

```bash
# clonar e entrar no projeto
git clone https://github.com/<seu-usuario>/finops-gpu-agent
cd finops-gpu-agent

# ambiente virtual
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# rodar com dados simulados (sem GPU, sem cloud, sem API key)
python main.py

# rodar todos os testes
pytest

# ver cobertura
pytest --cov=src
```

---

## Variáveis de ambiente

```bash
cp .env.example .env
# edite o .env com suas credenciais
```

| Variável | Padrão | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Chave da API do Claude |
| `METRICS_BACKEND` | `mock` | `mock` ou `prometheus` |
| `PROMETHEUS_URL` | `http://localhost:9090` | URL do Prometheus |
| `SLACK_WEBHOOK` | — | Webhook para notificações |
| `EVAL_INTERVAL_SECONDS` | `60` | Intervalo do loop principal |

---

## Prometheus local com Docker

```bash
cd infra/prometheus
docker compose up
```

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

Query de teste no Prometheus:
dcgm_gpu_utilization
dcgm_vram_utilization
gpu_job_duration_minutes

Depois sete `METRICS_BACKEND=prometheus` no `.env` e rode:
```bash
python main.py
```

---

## Testes

```bash
pytest                        # todos os testes
pytest tests/unit/            # só unitários
pytest tests/integration/     # só integração
pytest --cov=src --cov-report=term-missing
```

**46 testes, zero dependência de GPU ou cloud.**

Cada camada tem testes isolados:
- `test_policy_engine.py` — scores, rotas, circuit breaker, política por equipe
- `test_llm_contract.py` — contrato Pydantic: válidos e alucinações do LLM
- `test_mock_backend.py` — leitura do YAML e formato das métricas
- `test_audit_trace.py` — persistência, feedback loop, export de fixture
- `test_full_pipeline.py` — pipeline completo com LLM mockado

---

## Feedback loop

Após rodar o agente em produção, analise as decisões:

```bash
python scripts/analyze_feedback.py
```

O script lista rejeições humanas, erros de parsing do LLM e
gera sugestões concretas de ajuste no system prompt.
Para cada decisão rejeitada, gera automaticamente uma fixture pytest
para reproduzir o cenário e validar o ajuste.

---

## Roadmap

- [ ] Kubernetes Operator para `scale_down` real
- [ ] Integração com AWS Cost Explorer e GCP Billing API
- [ ] Dashboard Grafana com custo por time e por job
- [ ] Suporte a multi-cluster
- [ ] Alertas de anomalia com séries temporais (PromQL range queries)
- [ ] Interface web para aprovação human-in-the-loop

---

## Contexto

Projeto desenvolvido para estudar a combinação de
observabilidade de GPU, FinOps e agentes LLM com
arquitetura de produção — sem GPU, sem cloud, sem gastar nada.

Todo o desenvolvimento foi feito localmente com dados simulados.
A mesma arquitetura escala para produção trocando o `MockBackend`
pelo `PrometheusBackend` e configurando as variáveis de ambiente.
EOF
Verifique:
bashcat README.md | head -20

Agora o git init e primeiro commit:
bashgit init
git add .
git commit -m "feat: agente FinOps GPU com camada deterministica + LLM

- PolicyEngine com idle_score, vram_score e circuit breaker
- Contrato Pydantic para resposta do LLM
- AuditStore com rastreabilidade completa e export de fixture pytest
- MockBackend + Custom Collector Prometheus para dev sem GPU
- Docker Compose com Prometheus e Grafana
- 46 testes, zero dependencia de GPU ou cloud"
Depois crie o repositório no GitHub e:
bashgit remote add origin https://github.com/<seu-usuario>/finops-gpu-agent.git
git push -u origin main
