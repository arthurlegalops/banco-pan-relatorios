"""Login no elaw (Banco Pan)."""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

BASE_URL = "https://bancopan.elaw.com.br"
SCREENSHOTS_DIR = Path("logs") / "screenshots"
MAX_ATTEMPTS = 5
RETRY_DELAY = 2.0


class LoginError(Exception):
    """Falha ao autenticar no elaw."""


class SessionExpiredError(LoginError):
    """Sessão do elaw expirou durante o login."""


@dataclass(frozen=True)
class LoginConfig:
    email: str
    password: str
    base_url: str = BASE_URL

    @classmethod
    def from_env(cls) -> "LoginConfig":
        load_dotenv()
        email = os.getenv("EMAIL")
        password = os.getenv("PASS")
        if not email or not password:
            raise LoginError("Variáveis de ambiente EMAIL/PASS ausentes.")
        return cls(email=email, password=password)


def _is_session_expired_error(page: Page) -> bool:
    return "session-expired.htm" in page.url or "error" in page.url


def _click_acessar_button(page: Page) -> None:
    # Sem seletor HTML confiável para esse botão; clica na coordenada fixa
    # até navegar ou detectar sessão expirada.
    for _ in range(5):
        page.mouse.click(50, 150)
        page.wait_for_timeout(200)
        if _is_session_expired_error(page):
            break


def _capture_failure_screenshot(page: Page, stage: str) -> None:
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"{timestamp}_{stage}.png"
        page.screenshot(path=str(path), full_page=True)
        logger.info("Screenshot de diagnóstico salvo em: %s", path)
    except Exception as exc:
        logger.warning("Não foi possível capturar screenshot: %s", exc)


def _attempt_login(page: Page, config: LoginConfig) -> None:
    page.goto(f"{config.base_url}/", wait_until="domcontentloaded")
    if _is_session_expired_error(page):
        raise SessionExpiredError("Sessão expirada ao abrir a página de login.")

    page.fill('input[type="email"]', config.email)
    page.click('input[type="submit"]')

    page.fill('input[type="password"]', config.password)
    page.click('input[type="submit"]')

    page.wait_for_timeout(2000)
    if _is_session_expired_error(page):
        raise SessionExpiredError("Sessão expirada após preencher credenciais.")

    _click_acessar_button(page)
    if _is_session_expired_error(page):
        raise SessionExpiredError("Sessão expirada ao tentar acessar.")

    page.wait_for_selector("xpath=//*[@id='homePageGeral']")
    logger.info("Login realizado com sucesso!")


def login(
    page: Page,
    config: LoginConfig,
    on_step: Optional[Callable[[str, str, Optional[str]], None]] = None,
) -> None:
    """Realiza login no elaw, retentando em caso de sessão expirada/timeout.

    `on_step`, se informado, é chamado como `on_step(step_id, status, meta)`
    para reportar o progresso da etapa "login" à interface."""
    if on_step:
        on_step("login", "running", None)

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _attempt_login(page, config)
            if on_step:
                on_step("login", "done", None)
            return
        except (SessionExpiredError, PlaywrightTimeoutError) as exc:
            last_error = exc
            logger.warning("Tentativa %d/%d falhou: %s", attempt, MAX_ATTEMPTS, exc)
            page.context.clear_cookies()
            time.sleep(RETRY_DELAY)

    _capture_failure_screenshot(page, "login_falhou")
    erro = f"Falha ao realizar login após {MAX_ATTEMPTS} tentativas: {last_error}"
    if on_step:
        on_step("login", "error", erro)
    raise LoginError(erro)
