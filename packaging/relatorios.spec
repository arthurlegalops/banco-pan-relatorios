# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller: gera dist\\RelatoriosPan\\RelatoriosPan.exe
(servidor web FastAPI + automação do pipeline de relatórios).

O Chromium do Playwright NÃO é incluído aqui - é copiado por build.ps1
direto para dist\\RelatoriosPan\\pw-browsers\\ depois do build, pois
modules/browser.py já aponta PLAYWRIGHT_BROWSERS_PATH para essa pasta
quando empacotado.

O driver Node.js do Playwright (site-packages/playwright/driver/), por
outro lado, PRECISA estar aqui como `datas`: não existe hook do
PyInstaller para playwright, então sem isso sync_playwright() falha em
runtime ao tentar abrir o navegador.

`static/` (HTML/CSS/JS servidos pelo FastAPI) também precisa ir como
`datas` - o servidor não é executado a partir do código-fonte quando
empacotado, então esses arquivos não são achados automaticamente.

Este arquivo vive em packaging/, não na raiz do projeto - todos os caminhos
abaixo partem de PROJECT_ROOT (= packaging/../), e o script de entrada
("main.py") é resolvido relativo ao diretório de trabalho de onde o
PyInstaller é chamado (a raiz do projeto - ver build.ps1).
"""

from pathlib import Path

import playwright

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).parent
PW_DRIVER_DIR = Path(playwright.__file__).parent / "driver"
STATIC_DIR = PROJECT_ROOT / "static"

datas = [
    (str(PW_DRIVER_DIR), "playwright/driver"),
    (str(STATIC_DIR), "static"),
]

# Os módulos do uvicorn abaixo são resolvidos dinamicamente (auto-detecção
# de loop/protocolo) e escapam da análise estática do PyInstaller.
hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
]

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RelatoriosPan",
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="RelatoriosPan",
)
