"""Fluxo de pesquisa e exportação de relatórios no elaw: seleção de
filtros, execução da busca e exportação para Excel."""

import logging
import time

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

SEARCH_URL = "https://bancopan.elaw.com.br/processoList.elaw"
PAUTA_GERAL_URL = "https://bancopan.elaw.com.br/agendamentoContenciosoList.elaw"

# A pesquisa da pauta geral cobre todos os processos do ano inteiro e pode
# demorar bem mais que o padrão do Playwright (30s) para terminar.
PAUTA_GERAL_SEARCH_TIMEOUT = 600_000

# Tempo de espera após abrir o campo de seleção do modelo de relatório e
# antes de começar a digitar — sem essa pausa o campo às vezes ainda não
# está pronto para receber texto e o modelo é digitado errado.
MODELO_RELATORIO_DELAY_MS = 800

REPORT_NAMES = ["DADOS DO PROCESSO", "ESCRITÓRIO - TAREFAS"]
PAUTA_GERAL_NOME = "PAUTA GERAL"

REPORT_FILE_PREFIXES = {
    "DADOS DO PROCESSO": "DADOS_DO_PROCESSO",
    "ESCRITÓRIO - TAREFAS": "TAREFAS_ESCRITORIO",
    PAUTA_GERAL_NOME: "PAUTA_GERAL",
}

CHECKBOX_XPATHS = [
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[2]/div',
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[3]/div',
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[4]/div',
    '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[5]/div',
]


def selecionar_filtros(page: Page) -> None:
    logger.info("Selecionando filtros...")
    page.locator('//*[@id="tabSearchTab:comboStatus"]/div[3]').click()
    page.wait_for_selector(
        '//*[@id="tabSearchTab:comboStatus_panel"]/div[2]/ul/li[2]')

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
    page.wait_for_timeout(MODELO_RELATORIO_DELAY_MS)
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
        raise RuntimeError(
            f"Não foi possível capturar o ID do relatório '{nome_relatorio}'.")

    relatorio_id = valor_capturado.strip()
    logger.info(
        f"Relatório '{nome_relatorio}' exportado com ID: {relatorio_id}")

    page.frame_locator("iframe").locator('xpath=//*[@id="j_id_10"]').click()
    page.wait_for_timeout(4000)
    page.wait_for_load_state("networkidle")

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
    page.locator(
        '//*[@id="btnExcelProcesso"]').click(timeout=PAUTA_GERAL_SEARCH_TIMEOUT)

    page.frame_locator("iframe").locator(
        'xpath=//*[@id="selectProcessoReport_label"]').click()
    page.wait_for_timeout(MODELO_RELATORIO_DELAY_MS)
    page.keyboard.type(PAUTA_GERAL_NOME, delay=100)
    page.keyboard.press("Enter")
    page.frame_locator("iframe").locator(
        'xpath=//*[@id="btnGerarExcelProcessoReport"]').click()

    page.wait_for_timeout(1000)
    valor_capturado = page.frame_locator("iframe").locator(
        'xpath=//*[@id="panelProcessoReport"]/table[2]/tbody/tr[2]/td/table/tbody/tr[1]/td[2]'
    ).text_content()

    if not valor_capturado or not valor_capturado.strip():
        raise RuntimeError(
            f"Não foi possível capturar o ID do relatório '{PAUTA_GERAL_NOME}'.")

    relatorio_id = valor_capturado.strip()
    logger.info(
        f"Relatório '{PAUTA_GERAL_NOME}' exportado com ID: {relatorio_id}")
    return relatorio_id
