"""
QuickVET PRO - Testes Automatizados
===================================

Estrutura de testes:
- tests/unit/         - Testes unitários (sem dependências externas)
- tests/integration/  - Testes de integração (com banco, redis)
- tests/e2e/          - Testes end-to-end (API completa)

Executar todos os testes:
    pytest

Executar com cobertura:
    pytest --cov=app --cov-report=html

Executar testes específicos:
    pytest tests/unit/
    pytest tests/integration/
    pytest -k "test_search"
"""
