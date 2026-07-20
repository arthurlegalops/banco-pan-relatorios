"""Fluxo de pesquisa e exportação de relatórios no elaw: seleção de
filtros, execução da busca e exportação para Excel."""

import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

SEARCH_URL = "https://bancopan.elaw.com.br/processoList.elaw"
PAUTA_GERAL_URL = "https://bancopan.elaw.com.br/agendamentoContenciosoList.elaw"

# Pasta local (não depende de OneDrive/rede) — os relatórios ficam aqui
# temporariamente até o usuário baixá-los pelo painel web.
BASE_REPORTS_DIR = Path(__file__).resolve().parent.parent / "temp"
RETENCAO_DIAS = 7

# A pesquisa da pauta geral cobre todos os processos do ano inteiro e pode
# demorar bem mais que o padrão do Playwright (30s) para terminar.
PAUTA_GERAL_SEARCH_TIMEOUT = 600_000


def criar_pasta_dia(base: Path = BASE_REPORTS_DIR) -> Path:
    """Cria (se necessário) e retorna a pasta `<base>/AAAA-MM-DD`
    onde os relatórios do dia devem ser salvos."""
    data = time.strftime("%Y-%m-%d")
    pasta = base / data
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def limpar_relatorios_antigos(base: Path = BASE_REPORTS_DIR, dias: int = RETENCAO_DIAS) -> None:
    """Remove subpastas `AAAA-MM-DD` de `base` com mais de `dias` dias —
    os relatórios ficam disponíveis para download pelo painel só por esse
    período. Pastas com nome fora do padrão de data são ignoradas."""
    if not base.exists():
        return

    limite = datetime.now() - timedelta(days=dias)
    for pasta in base.iterdir():
        if not pasta.is_dir():
            continue
        try:
            data_pasta = datetime.strptime(pasta.name, "%Y-%m-%d")
        except ValueError:
            continue
        if data_pasta < limite:
            logger.info(f"Removendo relatórios expirados em: {pasta}")
            shutil.rmtree(pasta, ignore_errors=True)


REPORT_NAMES = ["DADOS DO PROCESSO", "ESCRITÓRIO - TAREFAS"]
PAUTA_GERAL_NOME = "PAUTA GERAL"

REPORT_FILE_PREFIXES = {
    "DADOS DO PROCESSO": "DADOS_DO_PROCESSO",
    "ESCRITÓRIO - TAREFAS": "TAREFAS_ESCRITORIO",
    PAUTA_GERAL_NOME: "PAUTA_GERAL",
}


def relatorio_existente(pasta: Path, nome_relatorio: str) -> Path | None:
    """Retorna o caminho do relatório de `nome_relatorio` já gerado em
    `pasta` (o mais recente, se houver mais de um), ou `None` se ainda
    não foi gerado nessa pasta."""
    prefixo = REPORT_FILE_PREFIXES[nome_relatorio]
    encontrados = sorted(pasta.glob(f"{prefixo}_*.xlsx"))
    return encontrados[-1] if encontrados else None


def relatorios_existentes(pasta: Path) -> dict[str, Path]:
    """Retorna, para cada relatório já gerado em `pasta` dentre
    `REPORT_NAMES + [PAUTA_GERAL_NOME]`, o mapeamento nome -> caminho."""
    todos_nomes = REPORT_NAMES + [PAUTA_GERAL_NOME]
    existentes = {}
    for nome in todos_nomes:
        caminho = relatorio_existente(pasta, nome)
        if caminho:
            existentes[nome] = caminho
    return existentes


def perguntar_ids_em_processamento(nomes: list[str]) -> dict[str, str]:
    """Para cada nome em `nomes`, pergunta ao usuário o ID de um relatório
    que já esteja em processamento no elaw (ex.: fluxo anterior interrompido
    antes do download). Retorna {nome: id} apenas para as respostas não
    vazias — os demais seguem o fluxo normal de exportação."""
    ids: dict[str, str] = {}
    for nome in nomes:
        resposta = input(f"ID do relatório '{nome}' já em processamento (Enter se não houver): ").strip()
        if resposta:
            ids[nome] = resposta
    return ids

CHECKBOX_XPATHS = [
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[2]/div',
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[3]/div',
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[4]/div',
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[5]/div',
]


def selecionar_filtros(page: Page) -> None:
    logger.info("Selecionando filtros...")
    page.locator('//*[@id="tabSearchTab:comboStatus"]/div[3]').click()
    page.wait_for_selector('//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[2]')

    for xpath in CHECKBOX_XPATHS:
        page.locator(xpath).click()
        page.wait_for_timeout(300)

    page.keyboard.press("Escape")


def executar_pesquisa(page: Page) -> None:
    logger.info("Clicando no botão de pesquisar...")
    page.locator('//*[@id="btnPesquisar"]').click()
    page.wait_for_load_state("networkidle")


def exportar_para_excel(page: Page, nome_relatorio: str) -> str:
    logger.info(f"Exportando relatório '{nome_relatorio}' para Excel...")
    page.locator('//*[@id="btnExcel"]').click()
    page.frame_locator("iframe").locator(
        "xpath=/html/body/div[1]/div/form/table[1]/tbody/tr/td[2]/div/label"
    ).click()
    page.keyboard.type(nome_relatorio, delay=100)
    page.keyboard.press("Enter")
    page.frame_locator("iframe").locator(
        "xpath=/html/body/div[1]/div/form/table[2]/tbody/tr/td[1]/button"
    ).click()

    page.wait_for_timeout(1000)
    valor_capturado = page.frame_locator("iframe").locator(
        "xpath=/html/body/div[1]/div/form/div[2]/table[2]/tbody/tr[2]/td/table/tbody/tr[1]/td[2]"
    ).text_content()

    if not valor_capturado or not valor_capturado.strip():
        raise RuntimeError(f"Não foi possível capturar o ID do relatório '{nome_relatorio}'.")

    relatorio_id = valor_capturado.strip()
    logger.info(f"Relatório '{nome_relatorio}' exportado com ID: {relatorio_id}")

    page.frame_locator("iframe").locator('xpath=//*[@id="j_id_10"]').click()
    page.wait_for_timeout(2000)

    return relatorio_id


def exportar_pauta_geral(page: Page) -> str:
    logger.info(f"Exportando relatório '{PAUTA_GERAL_NOME}' para Excel...")
    page.goto(PAUTA_GERAL_URL, wait_until="domcontentloaded")

    ano_atual = time.strftime("%Y")

    data_from = page.locator('//*[@id="tabSearchTab:dataFrom_input"]')
    data_from.fill("")
    data_from.type("01/01/2024", delay=100)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
    page.keyboard.press("Escape")

    data_to = page.locator('//*[@id="tabSearchTab:dataTo_input"]')
    data_to.fill("")
    data_to.type(f"31/12/{ano_atual} 23:59", delay=100)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
    page.keyboard.press("Escape")

    page.locator('//*[@id="tabSearchTab:status:1"]').click()
    page.locator('//*[@id="tabSearchTab:status:2"]').click()

    logger.info("Pesquisando pauta geral (pode demorar, cobre o ano inteiro)...")
    page.locator('//*[@id="tabSearchTab:btnPesquisar"]').click(timeout=120000)
    page.wait_for_load_state("networkidle", timeout=PAUTA_GERAL_SEARCH_TIMEOUT)
    page.locator('//*[@id="btnExcelProcesso"]').click(timeout=PAUTA_GERAL_SEARCH_TIMEOUT)

    page.frame_locator("iframe").locator('xpath=//*[@id="selectProcessoReport_label"]').click()
    page.keyboard.type(PAUTA_GERAL_NOME, delay=100)
    page.keyboard.press("Enter")
    page.frame_locator("iframe").locator('xpath=//*[@id="btnGerarExcelProcessoReport"]').click()

    page.wait_for_timeout(1000)
    valor_capturado = page.frame_locator("iframe").locator(
        'xpath=//*[@id="panelProcessoReport"]/table[2]/tbody/tr[2]/td/table/tbody/tr[1]/td[2]'
    ).text_content()

    if not valor_capturado or not valor_capturado.strip():
        raise RuntimeError(f"Não foi possível capturar o ID do relatório '{PAUTA_GERAL_NOME}'.")

    relatorio_id = valor_capturado.strip()
    logger.info(f"Relatório '{PAUTA_GERAL_NOME}' exportado com ID: {relatorio_id}")
    return relatorio_id
