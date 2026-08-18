"""Tipos e helpers para reportar o progresso do pipeline à interface."""

from typing import Callable, Optional

OnStep = Optional[Callable[[str, str, Optional[str]], None]]
OnReport = Optional[Callable[[str, str, Optional[str]], None]]


def emit_step(on_step: OnStep, step_id: str, status: str, meta: Optional[str] = None) -> None:
    if on_step:
        on_step(step_id, status, meta)


def emit_report(on_report: OnReport, nome: str, status: str, chave: Optional[str] = None) -> None:
    """`chave` é a chave S3 do relatório — só informada (e relevante) no
    status "downloaded", momento em que a interface pode gravá-la no banco
    para liberar o botão de download dessa execução."""
    if on_report:
        on_report(nome, status, chave)
