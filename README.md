# 🚀 GPU FinOps Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)

Agente de otimização de custos de GPU com camada determinística + LLM. Detecta GPUs ociosas, consumo anômalo e age automaticamente — sem delegar decisões críticas ao LLM.

## 📋 Tabela de Conteúdos

- [Problema](#-problema)
- [Solução](#-solução)
- [Arquitetura](#-arquitetura)
- [Decisões de Design](#-decisões-de-design)
- [Stack Tecnológica](#-stack-tecnológica)
- [Início Rápido](#-início-rápido)
- [Configuração](#-configuração)
- [Testes](#-testes)
- [Monitoramento](#-monitoramento)
- [Roadmap](#-roadmap)
- [Contribuição](#-contribuição)
- [Licença](#-licença)

## 🎯 Problema

GPU idle é um dos maiores drenos de budget em infraestrutura de ML. Em ambientes com múltiplos times e centenas de jobs, é comum ter **30-40% do spend desperdiçado** em recursos que ninguém está usando.

**Desafios:**
- ❌ Soluções baseadas só em alertas geram fadiga
- ❌ Soluções baseadas só em LLM são arriscadas (alucinação)
- ❌ Decisões críticas não podem ser delegadas cegamente

## 💡 Solução

Este agente resolve com uma **arquitetura de duas camadas**:

- **Camada Determinística** → Age quando tem certeza (score ≥ 0.85)
- **LLM** → Chamado apenas quando o contexto é ambíguo (score 0.50–0.84)
- **Princípio Central**: O LLM **nunca executa ação diretamente**

## 🏗️ Arquitetura

```mermaid
graph TD
    A[Alert/Metrics] --> B[PolicyEngine]
    
    B --> C{Score ≥ 0.85?}
    B --> D{Score 0.50-0.84?}
    B --> E{Score < 0.50?}
    
    C --> F[AUTO_ACT]
    F --> G[ActionExecutor]
    
    D --> H[CALL_LLM]
    H --> I[LLM Advisor]
    I --> J[Pydantic Validation]
    J --> G
    
    E --> K[IGNORE]
    
    B --> L{Circuit Breaker}
    L --> M[BLOCKED → Slack]
    
    G --> N[Audit Store]
    I --> N
    M --> N
