"""Tipos e helpers para reportar o progresso do pipeline à interface."""

from typing import Callable, Optional

OnStep = Optional[Callable[[str, str, Optional[str]], None]]
OnReport = Optional[Callable[[str, str], None]]


def emit_step(on_step: OnStep, step_id: str, status: str, meta: Optional[str] = None) -> None:
    if on_step:
        on_step(step_id, status, meta)


def emit_report(on_report: OnReport, nome: str, status: str) -> None:
    if on_report:
        on_report(nome, status)
