"""Envio de e-mail via Outlook (COM) com os relatórios anexados."""

import logging
from pathlib import Path

import win32com.client

logger = logging.getLogger(__name__)

DESTINATARIO = "checagem.pan@mascarenhasbarbosa.com.br"
ASSUNTO = "Relatórios elaw - Banco Pan"
CORPO = "Segue em anexo os relatórios extraídos do elaw."


def enviar_relatorios_por_email(anexos: list[Path]) -> None:
    """Envia os relatórios anexados por e-mail usando o Outlook instalado na máquina."""
    logger.info("Enviando relatórios por e-mail para %s...", DESTINATARIO)

    outlook = win32com.client.Dispatch("Outlook.Application")
    email = outlook.CreateItem(0)
    email.To = DESTINATARIO
    email.Subject = ASSUNTO
    email.Body = CORPO

    for anexo in anexos:
        email.Attachments.Add(str(anexo.resolve()))

    email.Send()
    logger.info("E-mail enviado com sucesso.")
