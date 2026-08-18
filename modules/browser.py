"""Ciclo de vida do navegador: abrir, logar e recuperar a sessão do elaw."""

import logging
import os
import sys

from modules.paths import APP_DIR

# Só redireciona quando empacotado (ver build.ps1/packaging/relatorios.spec):
# em dev, continua usando o cache padrão do Playwright
# (%LOCALAPPDATA%\ms-playwright), que já está populado nesta máquina — nada
# muda para quem roda `python server.py` direto do código-fonte. No .exe
# empacotado, aponta para {app}\pw-browsers (copiado por build.ps1) em vez
# do cache do usuário, que não existe numa instalação limpa. Precisa ser
# setado antes de qualquer uso do Playwright (ver `sync_playwright()` em
# main.py).
if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(APP_DIR / "pw-browsers"))

from playwright.sync_api import Browser, Page, Playwright  # noqa: E402

from modules.login import LoginConfig, login  # noqa: E402
from modules.progress import OnStep  # noqa: E402

logger = logging.getLogger(__name__)


class SessaoElaw:
    """Mantém um navegador logado no elaw, permitindo recriá-lo em caso de
    queda de sessão."""

    def __init__(self, playwright: Playwright, config: LoginConfig, on_step: OnStep = None):
        self._playwright = playwright
        self._config = config
        self._on_step = on_step
        self.browser, self.page = self._abrir()

    def _abrir(self) -> tuple[Browser, Page]:
        browser = self._playwright.chromium.launch(
            headless=False, args=["--disable-save-password-bubble"])
        page = browser.new_page()
        login(page, self._config, on_step=self._on_step)
        return browser, page

    def recover(self) -> Page:
        """Fecha o navegador atual, reabre e refaz o login. Retorna a nova página."""
        logger.warning("Reabrindo navegador e refazendo login...")
        self.browser.close()
        self.browser, self.page = self._abrir()
        return self.page

    def close(self) -> None:
        self.browser.close()

    def cancelar(self) -> None:
        """Força o fechamento do navegador a partir de outra thread (ex.:
        requisição HTTP de cancelamento) para interromper imediatamente
        qualquer chamada do Playwright em andamento na thread do pipeline."""
        try:
            self.browser.close()
        except Exception:
            pass
