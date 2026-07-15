"""Orquestra a pesquisa de processos no elaw e a exportação/download dos
relatórios "DADOS DO PROCESSO", "ESCRITÓRIO - TAREFAS" e "PAUTA GERAL"."""

import logging
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page

from modules.download import aguardar_e_baixar_relatorios
from modules.elaw import (
    PAUTA_GERAL_NOME,
    REPORT_NAMES,
    SEARCH_URL,
    exportar_para_excel,
    exportar_pauta_geral,
    executar_pesquisa,
    selecionar_filtros,
)
from modules.progress import OnReport, OnStep, emit_report, emit_step

logger = logging.getLogger(__name__)


def pesquisar(
    page: Page,
    recover: Callable[[], Page],
    download_dir: Path,
    existentes: dict[str, Path],
    on_step: OnStep = None,
    on_report: OnReport = None,
) -> list[Path]:
    """Aplica os filtros de status, pesquisa, exporta os relatórios
    "DADOS DO PROCESSO", "ESCRITÓRIO - TAREFAS" e "PAUTA GERAL", aguarda
    todos ficarem prontos e baixa todos em `download_dir`.

    `existentes` traz os relatórios do dia já gerados anteriormente
    (nome -> caminho), verificados antes de abrir o navegador; apenas os
    relatórios ausentes desse dict são exportados/baixados aqui.

    `recover` fecha o navegador atual, abre um novo, refaz o login e
    retorna a nova página — usado caso a sessão caia durante a espera
    do processamento dos relatórios.

    `on_step` e `on_report`, se informados, são chamados para reportar o
    progresso do pipeline e o status de cada relatório à interface."""
    todos_nomes = REPORT_NAMES + [PAUTA_GERAL_NOME]

    pendentes_geral = [nome for nome in REPORT_NAMES if nome not in existentes]
    pauta_pendente = PAUTA_GERAL_NOME not in existentes

    relatorio_ids: dict[str, str] = {}

    if pendentes_geral:
        logger.info("Navegando para a página de pesquisa...")
        page.goto(SEARCH_URL, wait_until="domcontentloaded")

        emit_step(on_step, "filtros", "running")
        selecionar_filtros(page)
        emit_step(on_step, "filtros", "done")

        emit_step(on_step, "pesquisa", "running")
        executar_pesquisa(page)
        emit_step(on_step, "pesquisa", "done")

    emit_step(on_step, "exportacao", "running")
    for nome in pendentes_geral:
        emit_report(on_report, nome, "waiting")
        relatorio_ids[nome] = exportar_para_excel(page, nome)
    if pauta_pendente:
        emit_report(on_report, PAUTA_GERAL_NOME, "waiting")
        relatorio_ids[PAUTA_GERAL_NOME] = exportar_pauta_geral(page)
    emit_step(on_step, "exportacao", "done")

    emit_step(on_step, "aguardar", "running")
    emit_step(on_step, "download", "running")
    baixados, page = aguardar_e_baixar_relatorios(page, relatorio_ids, recover, download_dir, on_report)
    emit_step(on_step, "aguardar", "done")
    emit_step(on_step, "download", "done")

    resultado = {**existentes, **baixados}
    return [resultado[nome] for nome in todos_nomes]
