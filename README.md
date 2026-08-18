# Painel de Relatórios — Banco Pan (eLaw)

Aplicativo desktop (Tkinter) que automatiza a exportação dos relatórios do
eLaw ("DADOS DO PROCESSO", "ESCRITÓRIO - TAREFAS" e "PAUTA GERAL"), envia os
arquivos para um bucket S3 compartilhado e registra o histórico de execuções
num MongoDB remoto — para que qualquer máquina veja o mesmo status e os
mesmos relatórios, independente de quem rodou a automação.

## Arquitetura

- **`gui.py`** — interface Tkinter (lista de execuções, log ao vivo, botões
  de download). Ponto de entrada da aplicação.
- **`main.py` / `pesquisar.py`** — orquestração do pipeline de automação
  (login, filtros, exportação, download).
- **`modules/`**
  - `browser.py`, `login.py`, `elaw.py`, `download.py`, `cancel.py`,
    `progress.py` — automação Playwright do eLaw.
  - `storage.py` — upload/download dos relatórios no S3.
  - `history.py` — histórico de execuções no MongoDB (status, downloads).
  - `paths.py` — resolução de caminhos (dev vs. `.exe` empacotado).
- **`packaging/`** — script do PyInstaller (`.spec`) e do Inno Setup
  (`.iss`) para gerar o instalador Windows.

## Configuração

Credenciais e conexões ficam num `.env` na raiz do projeto (nunca versionado
— veja `.gitignore`):

```
EMAIL=...
PASS=...

AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=...

MONGO_URI=mongodb://usuario:senha@host:porta/relatorios?authSource=admin
```

As credenciais do eLaw também podem ser editadas em runtime pela própria
GUI (botão "Credenciais").

## Rodando em desenvolvimento

```bash
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium
python gui.py
```

## Build (instalador Windows)

```powershell
./build.ps1
```

Gera `dist/RelatoriosPan/` (via PyInstaller) usando `VERSION` como fonte
única de versão. O instalador final (`Setup.exe`) é gerado a partir de
`packaging/relatorios.iss` (Inno Setup), que depende da pasta `dist/` já
existir.
