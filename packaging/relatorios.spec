# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller: gera dist\\RelatoriosPan\\ com o executável único
RelatoriosPan.exe (GUI Tkinter + automação do pipeline de relatórios).

O Chromium do Playwright NÃO é incluído aqui - é copiado por build.ps1
direto para dist\\RelatoriosPan\\pw-browsers\\ depois do build, pois
modules/browser.py já aponta PLAYWRIGHT_BROWSERS_PATH para essa pasta
quando empacotado.

O driver Node.js do Playwright (site-packages/playwright/driver/), por
outro lado, PRECISA estar aqui como `datas`: não existe hook do
PyInstaller para playwright, então sem isso sync_playwright() falha em
runtime ao tentar abrir o navegador.

Tkinter é da biblioteca padrão - o PyInstaller já tem hook embutido pra
ele, não precisa de `datas`/`hiddenimports` extra.

Este arquivo vive em packaging/, não na raiz do projeto - todos os caminhos
abaixo partem de PROJECT_ROOT (= packaging/../), e o script de entrada
("gui.py") é resolvido relativo ao diretório de trabalho de onde o
PyInstaller é chamado (a raiz do projeto - ver build.ps1).
"""

from pathlib import Path

import playwright

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).parent
PW_DRIVER_DIR = Path(playwright.__file__).parent / "driver"

datas = [(str(PW_DRIVER_DIR), "playwright/driver")]

a = Analysis(
    [str(PROJECT_ROOT / "gui.py")],
    pathex=[str(PROJECT_ROOT)],
    datas=datas,
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
