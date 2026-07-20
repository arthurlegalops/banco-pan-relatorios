import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

from modules.browser import SessaoElaw
from modules.elaw import (
    PAUTA_GERAL_NOME,
    REPORT_NAMES,
    criar_pasta_dia,
    limpar_relatorios_antigos,
    perguntar_ids_em_processamento,
    relatorios_existentes,
)
from modules.login import LoginConfig
from modules.progress import OnReport, OnStep, emit_report
from pesquisar import pesquisar

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

logger = logging.getLogger(__name__)


def executar(
    ids_informados: dict[str, str] | None = None,
    on_step: OnStep = None,
    on_report: OnReport = None,
) -> list[Path]:
    """Executa o pipeline completo (login, pesquisa, exportação e download
    dos relatórios) e retorna os caminhos dos arquivos baixados.

    `ids_informados` traz relatórios já em processamento no elaw de uma
    execução anterior interrompida (nome -> ID) — usado apenas pelo fluxo
    de linha de comando (`main()`); a execução via web nunca informa isso.

    `on_step`/`on_report`, se informados, recebem atualizações de progresso
    — usados pela interface web para acompanhar a execução em tempo real."""
    limpar_relatorios_antigos()
    download_dir = criar_pasta_dia()
    todos_nomes = REPORT_NAMES + [PAUTA_GERAL_NOME]
    existentes = relatorios_existentes(download_dir)

    if len(existentes) == len(todos_nomes):
        logger.info(f"Todos os relatórios do dia já existem em {download_dir}, navegador não será aberto.")
        for nome in todos_nomes:
            emit_report(on_report, nome, "downloaded")
        return [existentes[nome] for nome in todos_nomes]

    for nome, caminho in existentes.items():
        logger.info(f"Relatório '{nome}' já existe em {caminho}, pulando geração.")
        emit_report(on_report, nome, "downloaded")

    config = LoginConfig.from_env()

    with sync_playwright() as p:
        sessao = SessaoElaw(p, config, on_step)
        try:
            return pesquisar(
                sessao.page, sessao.recover, download_dir, existentes,
                ids_informados=ids_informados, on_step=on_step, on_report=on_report,
            )
        finally:
            sessao.close()


def main() -> None:
    download_dir = criar_pasta_dia()
    existentes = relatorios_existentes(download_dir)
    nomes_pendentes = [nome for nome in REPORT_NAMES + [PAUTA_GERAL_NOME] if nome not in existentes]
    ids_informados = perguntar_ids_em_processamento(nomes_pendentes) if nomes_pendentes else {}

    downloads = executar(ids_informados=ids_informados)
    print(f"Relatórios baixados: {downloads}")
    print("Pressione Enter para fechar...")
    input()


if __name__ == "__main__":
    main()
