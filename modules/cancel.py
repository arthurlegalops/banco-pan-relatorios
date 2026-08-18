"""Suporte a cancelamento cooperativo do pipeline pelo usuário."""

import threading


class ExecucaoCancelada(Exception):
    """Levantada quando o usuário cancela a execução em andamento."""


def checar_cancelamento(cancel_event: threading.Event | None) -> None:
    """Levanta `ExecucaoCancelada` se `cancel_event` estiver marcado.
    Chamado entre etapas do pipeline para interromper rapidamente sem
    esperar a próxima chamada do Playwright falhar por causa do navegador
    fechado (mecanismo usado para interromper esperas longas em andamento)."""
    if cancel_event is not None and cancel_event.is_set():
        raise ExecucaoCancelada("Execução cancelada pelo usuário.")
