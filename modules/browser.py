"""Ciclo de vida do navegador: abrir, logar e recuperar a sessão do elaw."""

import logging

from playwright.sync_api import Browser, Page, Playwright

from modules.login import LoginConfig, login
from modules.progress import OnStep

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
