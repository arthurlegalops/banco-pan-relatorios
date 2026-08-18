"""Resolução de caminhos que dependem de o app estar rodando a partir do
código-fonte (dev) ou empacotado pelo PyInstaller (frozen, ver packaging/)."""

import sys
from pathlib import Path

# Quando empacotado (onedir), `__file__` aponta para dentro de `_internal\`
# (pasta com os dados/bibliotecas empacotados, sobrescrita a cada instalação/
# atualização) — não para onde o .exe realmente está. `sys.executable` é o
# caminho correto nesse caso, e é onde dados mutáveis (runs.db, logs/,
# pw-browsers/) precisam ficar para sobreviver a uma atualização.
# Em desenvolvimento, sobe de modules/ para a raiz do projeto.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent

# Pouso temporário do Playwright antes do upload pro S3 (ver
# modules/download.py) — o Playwright só sabe salvar em disco local, nunca
# direto num destino remoto. Cada arquivo é apagado daqui assim que o
# upload termina; o S3 é a fonte da verdade, não esta pasta.
TEMP_DOWNLOADS_DIR = APP_DIR / "temp_downloads"
