"""Fluxo de polling e download dos relatórios exportados no elaw."""

import logging
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page

from modules.elaw import REPORT_FILE_PREFIXES
from modules.progress import OnReport, emit_report

logger = logging.getLogger(__name__)

REPORT_LIST_URL = "https://bancopan.elaw.com.br/userProcessoReportTmpList.elaw?faces-redirect=true"

POLL_TIMEOUT = 3600
POLL_INTERVAL_MS = 60000
POLL_MAX_ATTEMPTS = 3
POLL_RETRY_DELAY = 2.0


def _clip_selector(relatorio_id: str) -> str:
    row_selector = f"//tbody[@id='tableProcessoReportTmp_data']/tr[td[3][text()='{relatorio_id}']]"
    return f"{row_selector}//img[contains(@title, 'pronto para download') or contains(@src, 'clip')]"


def _baixar_relatorio(page: Page, nome_relatorio: str, clip_selector: str, download_dir: Path) -> Path:
    logger.info(f"Baixando relatório '{nome_relatorio}'...")
    with page.expect_download() as download_info:
        page.locator(clip_selector).click()
    download = download_info.value

    sugerido = download.suggested_filename or ""
    extensao = Path(sugerido).suffix or ".xlsx"
    prefixo = REPORT_FILE_PREFIXES.get(nome_relatorio, nome_relatorio.replace(" ", "_"))
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{prefixo}_{timestamp}{extensao}"
    download_path = download_dir / filename
    download.save_as(str(download_path))
    logger.info(f"Relatório '{nome_relatorio}' salvo em: {download_path}")
    return download_path


def aguardar_e_baixar_relatorios(
    page: Page,
    relatorio_ids: dict[str, str],
    recover: Callable[[], Page],
    download_dir: Path,
    on_report: OnReport = None,
) -> tuple[dict[str, Path], Page]:
    """Faz polling e baixa cada relatório assim que ele ficar pronto, sem
    esperar os demais. Retorna um dict {nome_relatorio: caminho_baixado} e a
    página (possivelmente recriada) em uso."""
    logger.info("Navegando para a lista de relatórios...")
    page.goto(REPORT_LIST_URL, wait_until="domcontentloaded")

    pendentes = dict(relatorio_ids)
    baixados: dict[str, Path] = {}
    page_ref = [page]

    start_time = time.monotonic()
    while pendentes and time.monotonic() - start_time < POLL_TIMEOUT:
        for tentativa in range(1, POLL_MAX_ATTEMPTS + 1):
            try:
                page_ref[0].locator('//*[@id="btnPesquisar"]').click()
                page_ref[0].wait_for_selector("#tableProcessoReportTmp_data", timeout=10000)
                break
            except Exception as exc:
                if tentativa == POLL_MAX_ATTEMPTS:
                    logger.warning(
                        f"Erro persistente ao atualizar a lista de relatórios: {exc}. "
                        "Reabrindo navegador, refazendo login e voltando à página de relatórios..."
                    )
                    page_ref[0] = recover()
                    page_ref[0].goto(REPORT_LIST_URL, wait_until="domcontentloaded")
                else:
                    logger.warning(f"Erro temporário ao atualizar a lista de relatórios ({tentativa}/{POLL_MAX_ATTEMPTS}): {exc}")
                    time.sleep(POLL_RETRY_DELAY)

        for nome, relatorio_id in list(pendentes.items()):
            clip = _clip_selector(relatorio_id)
            if page_ref[0].locator(clip).count() > 0:
                logger.info(f"Relatório '{nome}' (ID {relatorio_id}) pronto para download.")
                emit_report(on_report, nome, "ready")
                baixados[nome] = _baixar_relatorio(page_ref[0], nome, clip, download_dir)
                emit_report(on_report, nome, "downloaded")
                del pendentes[nome]
            else:
                logger.info(f"Relatório '{nome}' (ID {relatorio_id}) ainda em processamento.")

        if pendentes:
            page_ref[0].wait_for_timeout(POLL_INTERVAL_MS)

    if pendentes:
        faltantes = ", ".join(f"{nome} (ID {rid})" for nome, rid in pendentes.items())
        raise TimeoutError(f"Relatório(s) não terminaram de processar em até {POLL_TIMEOUT}s: {faltantes}")

    return baixados, page_ref[0]
