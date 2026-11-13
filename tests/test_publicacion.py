"""Producción se publica a mano: un push a dev corre los tests (y deploya staging) pero no adelanta main."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci-promote.yml"


def test_main_solo_se_adelanta_a_mano_y_desde_dev():
    texto = WORKFLOW.read_text()
    assert "if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/dev'" in texto
    assert "github.event_name != 'pull_request'" not in texto  # la condición vieja publicaba con cada push a dev


def test_los_tests_siguen_corriendo_en_cada_push_y_pr_a_dev():
    texto = WORKFLOW.read_text()
    assert "push:\n    branches: [dev]" in texto and "pull_request:\n    branches: [dev, main]" in texto
    assert "workflow_dispatch:" in texto
