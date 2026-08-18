"""Armazenamento dos relatórios gerados, no S3 (bucket compartilhado do
escritório) — substitui a antiga pasta local sincronizada por
OneDrive/SharePoint. Toda a interação com S3 fica concentrada aqui, para
`modules/elaw.py` continuar só com automação de página do eLaw."""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import boto3
from dotenv import load_dotenv

from modules.elaw import PAUTA_GERAL_NOME, REPORT_FILE_PREFIXES, REPORT_NAMES
from modules.paths import APP_DIR

logger = logging.getLogger(__name__)

# Diferente de modules/login.py (que usa `dotenv_values()` para nunca
# cachear, porque a GUI edita as credenciais do eLaw em runtime): aqui não
# existe tela de editar credencial AWS, então basta popular `os.environ`
# uma vez no import — `boto3.client(...)` já lê AWS_ACCESS_KEY_ID/
# AWS_SECRET_ACCESS_KEY/AWS_REGION de lá sozinho, sem precisar passar nada
# explícito.
load_dotenv(APP_DIR / ".env")

S3_BUCKET = "mascarenhas-lake"
S3_PREFIX_BASE = "operacional/orquestra/banco-pan/relatorios"

_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
    return _client


def pasta_do_dia() -> str:
    """Retorna `AAAA-MM-DD` de hoje — o "subdiretório" (na verdade só um
    prefixo de chave) onde os relatórios do dia ficam no S3."""
    return time.strftime("%Y-%m-%d")


def chave(pasta: str, nome_arquivo: str) -> str:
    return f"{S3_PREFIX_BASE}/{pasta}/{nome_arquivo}"


_chave = chave


def relatorio_existente(pasta: str, nome_relatorio: str) -> Optional[str]:
    """Retorna a chave S3 do relatório de `nome_relatorio` já gerado hoje
    (a mais recente, se houver mais de uma), ou `None` se ainda não existe."""
    prefixo = REPORT_FILE_PREFIXES[nome_relatorio]
    resp = _s3().list_objects_v2(
        Bucket=S3_BUCKET, Prefix=_chave(pasta, prefixo) + "_")
    contents = resp.get("Contents", [])
    if not contents:
        return None
    # Nomes de arquivo terminam em AAAAMMDD_HHMMSS.xlsx — ordenação de
    # string bate com ordenação cronológica, igual ao `sorted(glob)[-1]`
    # que a versão local usava.
    mais_recente = max(contents, key=lambda obj: obj["Key"])
    return mais_recente["Key"]


def relatorios_existentes(pasta: str) -> dict[str, str]:
    """Retorna, para cada relatório já gerado hoje dentre
    `REPORT_NAMES + [PAUTA_GERAL_NOME]`, o mapeamento nome -> chave S3."""
    todos_nomes = REPORT_NAMES + [PAUTA_GERAL_NOME]
    existentes = {}
    for nome in todos_nomes:
        chave = relatorio_existente(pasta, nome)
        if chave:
            existentes[nome] = chave
    return existentes


def enviar_relatorio(caminho_local: Path, pasta: str) -> str:
    """Envia o arquivo local para o S3, na pasta do dia, e retorna a chave."""
    chave = _chave(pasta, caminho_local.name)
    _s3().upload_file(str(caminho_local), S3_BUCKET, chave)
    logger.info(f"Relatório enviado para s3://{S3_BUCKET}/{chave}")
    return chave


def baixar_para_local(chave: str, destino: Path) -> Path:
    """Baixa um objeto do S3 para o caminho local `destino` — usado para
    abrir o relatório localmente (ex.: no Excel)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    _s3().download_file(S3_BUCKET, chave, str(destino))
    return destino
