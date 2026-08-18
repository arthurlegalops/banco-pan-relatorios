"""Aplicativo desktop (Tkinter) do painel de Relatórios.

Substitui o antigo painel web (server.py + index.html/app.js/styles.css,
removidos). A lógica de automação (main.py, pesquisar.py, modules/*) não
muda nada — só a camada de apresentação.

Widgets nativos do tema do Windows (ttk, tema "vista") em toda a interface —
sem cores/relevos customizados imitando o design do painel web antigo. Cor
é usada só como sinal semântico (texto de status, linhas da tabela), nunca
para "repintar" botões/painéis por cima do tema nativo."""

import logging
import os
import re
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Optional

import modules.history as history
import modules.storage as storage
from main import executar
from modules.browser import SessaoElaw
from modules.cancel import ExecucaoCancelada
from modules.login import credenciais_atuais, salvar_credenciais
from modules.paths import APP_DIR, TEMP_DOWNLOADS_DIR

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOGS_DIR = APP_DIR / "logs" / "runs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Cor por categoria — usada só como texto/realce semântico (status, erro,
# linhas de tabela), nunca para customizar o visual de botões/painéis.
# ---------------------------------------------------------------------------

MUTED = "#6B6B6B"

CORES = {
    "verde": "#1F6B3A",
    "azul": "#2C57A0",
    "ambar": "#8A6414",
    "vermelho": "#A5372B",
    "cinza": "#5C5A56",
}
# fundo bem leve das mesmas categorias, só para linhas de tabela (destaque
# discreto de status numa lista, padrão comum mesmo em apps nativos — ex.:
# categorias do Outlook, cores condicionais do Excel).
CORES_LINHA = {
    "verde": "#E8F6EC",
    "azul": "#E9EFFA",
    "ambar": "#FBF3DE",
    "vermelho": "#FBEBE9",
    "cinza": "#F1F0EE",
}

RUN_STATUS_LABEL = {"running": "Em execução", "success": "Concluída", "error": "Erro", "cancelled": "Cancelada"}
RUN_STATUS_CATEGORIA = {"running": "azul", "success": "verde", "error": "vermelho", "cancelled": "cinza"}

_LOG_LINE_RE = re.compile(r"^(.*?) \[(\w+)\] (.*)$")


def fmt_data(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%d/%m/%Y %H:%M")


def _parse_log_line(line: str) -> Optional[tuple[str, str, str]]:
    m = _LOG_LINE_RE.match(line)
    if not m:
        return None
    prefix, level, message = m.groups()
    time_part = prefix.split(" ")[-1].split(",")[0]
    return time_part, level, message


# ---------------------------------------------------------------------------
# Log handler: grava cada execução em logs/runs/{id}.log e retransmite pra UI
# ---------------------------------------------------------------------------

class RunLogHandler(logging.Handler):
    def __init__(self, log_path: Path, on_line):
        super().__init__()
        # "w": cada run_id é sempre uma execução nova, nunca reaproveita
        # conteúdo de uma execução antiga com o mesmo id.
        self.file = open(log_path, "w", encoding="utf-8")
        self.on_line = on_line
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted = self.format(record)
            self.file.write(formatted + "\n")
            self.file.flush()
            self.on_line(datetime.now().strftime("%H:%M:%S"), record.levelname, record.getMessage())
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.file.close()
        finally:
            super().close()


# ---------------------------------------------------------------------------
# Diálogo de credenciais
# ---------------------------------------------------------------------------

class CredentialsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, on_saved):
        super().__init__(parent)
        self.on_saved = on_saved
        self.title("Credenciais do eLaw")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        pad = {"padx": 20}
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        font_family = tkfont.nametofont("TkDefaultFont").actual("family")
        email, tem_senha = credenciais_atuais()

        ttk.Label(body, text="Credenciais do eLaw", font=(font_family, 13, "bold")).pack(anchor="w", pady=(18, 4), **pad)
        ttk.Label(body, text="Usadas pelo robô para fazer login automaticamente no eLaw.\n"
                              "Ficam salvas só nesta máquina.",
                  foreground=MUTED, justify="left").pack(anchor="w", pady=(0, 14), **pad)

        ttk.Label(body, text="E-mail").pack(anchor="w", **pad)
        self.email_var = tk.StringVar(value=email)
        ttk.Entry(body, textvariable=self.email_var, width=42).pack(anchor="w", pady=(3, 12), **pad)

        ttk.Label(body, text="Senha").pack(anchor="w", **pad)
        self.senha_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.senha_var, width=42).pack(anchor="w", pady=(3, 3), **pad)
        placeholder = "Deixe em branco para manter a atual" if tem_senha else "Digite a senha"
        ttk.Label(body, text=placeholder, foreground=MUTED, font=(font_family, 8)).pack(anchor="w", pady=(0, 14), **pad)

        self.error_var = tk.StringVar()
        ttk.Label(body, textvariable=self.error_var, foreground=CORES["vermelho"]).pack(anchor="w", **pad)

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(4, 18), **pad)
        ttk.Button(btns, text="Salvar", command=self._save, default="active").pack(side="right")
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side="right", padx=(0, 8))

    def _save(self) -> None:
        email = self.email_var.get().strip()
        senha = self.senha_var.get()
        if not email:
            self.error_var.set("Preencha o e-mail.")
            return
        _, tem_senha = credenciais_atuais()
        if not senha and not tem_senha:
            self.error_var.set("Preencha a senha.")
            return
        salvar_credenciais(email, senha or None)
        self.on_saved()
        self.destroy()


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        # Família das fontes nativas do Tk (não fixamos "Segoe UI"/"Consolas"
        # no código — pegamos o que o Tk já resolveu como padrão do SO,
        # variando só tamanho/peso onde precisa de destaque).
        self.font_family = tkfont.nametofont("TkDefaultFont").actual("family")
        self.fixed_font_family = tkfont.nametofont("TkFixedFont").actual("family")
        root.title("Relatórios · Pan")
        # "+40+40" (não só "1500x800"): sem posição explícita o Tk tende a
        # abrir centralizado; um deslocamento fixo evita isso.
        root.geometry("1500x800+40+40")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.runs: list[dict] = []
        self.selected_run_id: Optional[int] = None
        self.live_run_id: Optional[int] = None
        self.live_running = False
        self.live_steps: dict[str, dict] = {}
        self.live_reports: dict[str, str] = {}
        self.live_log_lines: list[tuple[str, str, str]] = []
        self.cancel_event: Optional[threading.Event] = None
        self.sessao: Optional[SessaoElaw] = None
        self.run_lock = threading.Lock()
        self._status_after_id: Optional[str] = None

        history.init_db()
        self._build_ui()
        self._refresh_index()
        self._check_credenciais_banner()

    # ---------------- construção da UI ----------------

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")  # tema nativo do Windows (Aero/Fluent, conforme o SO)
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=26)

        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=24, pady=(20, 8))
        title_box = ttk.Frame(header)
        title_box.pack(side="left", anchor="w")
        ttk.Label(title_box, text="Relatórios · Pan", font=(self.font_family, 17, "bold")).pack(anchor="w")
        ttk.Label(title_box, text="Extração automática dos relatórios do eLaw — Dados do Processo, "
                                   "Escritório-Tarefas e Pauta Geral.",
                  foreground=MUTED).pack(anchor="w")

        actions_box = ttk.Frame(header)
        actions_box.pack(side="right", anchor="e")
        ttk.Button(actions_box, text="Credenciais", command=self._open_credentials).pack(side="left", padx=(0, 8))
        self.run_now_btn = ttk.Button(actions_box, text="▶ Executar agora", command=self._run_now, default="active")
        self.run_now_btn.pack(side="left")

        self.warning_label = ttk.Label(self.root, foreground=CORES["vermelho"])
        # empacotado/desempacotado por _check_credenciais_banner

        self.paned = ttk.PanedWindow(self.root, orient="horizontal")
        self.paned.pack(fill="both", expand=True, padx=24, pady=(4, 20))

        self._build_list_pane(self.paned)
        self._build_detail_pane(self.paned)

        self.status_label = ttk.Label(self.root, text="", anchor="w", padding=(6, 4))
        self.status_label.pack(fill="x", padx=24, pady=(0, 12))

    def _build_list_pane(self, paned: ttk.PanedWindow) -> None:
        frame = ttk.Frame(paned)
        # weight menor que o painel de detalhe (abaixo): a lista não precisa
        # de tanta largura (só 4 colunas curtas), e o log se beneficia mais
        # do espaço extra pra caber linhas compridas sem quebrar.
        paned.add(frame, weight=1)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="Execuções", font=(self.font_family, 10, "bold")).pack(side="left")
        ttk.Button(toolbar, text="↻ Atualizar", command=self._refresh_index).pack(side="right")

        columns = ("id", "inicio", "relatorios", "status")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("id", text="Execução")
        self.tree.heading("inicio", text="Início")
        self.tree.heading("relatorios", text="Relatórios")
        self.tree.heading("status", text="Status")
        self.tree.column("id", width=110, anchor="w")
        self.tree.column("inicio", width=130, anchor="w")
        self.tree.column("relatorios", width=220, anchor="w")
        self.tree.column("status", width=110, anchor="w")
        for categoria, bg in CORES_LINHA.items():
            self.tree.tag_configure(categoria, background=bg)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_detail_pane(self, paned: ttk.PanedWindow) -> None:
        frame = ttk.Frame(paned)
        paned.add(frame, weight=3)
        self.detail_frame = frame

        self.empty_label = ttk.Label(frame, text='Nenhuma execução selecionada. Clique em "Executar agora" para começar.',
                                      foreground=MUTED)
        self.empty_label.pack(pady=40)

        self.detail_content = ttk.Frame(frame)
        # empacotado/desempacotado conforme há ou não execução selecionada

        title_row = ttk.Frame(self.detail_content)
        title_row.pack(fill="x")
        self.detail_title_var = tk.StringVar()
        ttk.Label(title_row, textvariable=self.detail_title_var, font=(self.font_family, 14, "bold")).pack(side="left")
        self.detail_badge = ttk.Label(title_row, text="", font=(self.font_family, 9, "bold"))
        self.detail_badge.pack(side="left", padx=(10, 0))

        actions_row = ttk.Frame(self.detail_content)
        actions_row.pack(fill="x", pady=(8, 0))
        self.cancel_btn = ttk.Button(actions_row, text="Cancelar execução", command=self._cancel_run)

        self.detail_meta_var = tk.StringVar()
        ttk.Label(self.detail_content, textvariable=self.detail_meta_var, foreground=MUTED).pack(anchor="w", pady=(6, 0))

        self.error_var = tk.StringVar()
        self.error_label = ttk.Label(self.detail_content, textvariable=self.error_var, foreground=CORES["vermelho"],
                                      wraplength=640, justify="left")

        self.downloads_frame = ttk.Frame(self.detail_content)
        # empacotado/desempacotado por _render_downloads_row, um botão por
        # relatório já gerado (DADOS DO PROCESSO / ESCRITÓRIO-TAREFAS / PAUTA GERAL)

        # self.log_header é a âncora estável (nunca desempacotada) usada por
        # error_label/downloads_frame acima para se inserirem sempre na
        # posição certa via before=, mesmo eles sendo empacotados/
        # desempacotados a cada render.
        self.log_header = ttk.Frame(self.detail_content)
        self.log_header.pack(fill="x", pady=(14, 4))
        ttk.Label(self.log_header, text="Logs", foreground=MUTED).pack(side="left")
        ttk.Button(self.log_header, text="Abrir arquivo", command=self._abrir_log_arquivo).pack(side="right")
        ttk.Button(self.log_header, text="Copiar", command=self._copy_log).pack(side="right", padx=(0, 6))

        # width=140: largura natural generosa (a maioria das linhas de log
        # cabe sem quebrar) — puxa o painel de detalhe inteiro pra ser mais
        # largo já na abertura, sem precisar fixar a posição do divisor do
        # PanedWindow por código (frágil: só funciona de forma confiável
        # depois que a janela já foi mapeada na tela).
        self.log_text = ScrolledText(self.detail_content, height=22, width=140, bg="#FFFFFF", fg="#1E1E1E",
                                      insertbackground="#1E1E1E", font=(self.fixed_font_family, 9), relief="flat", wrap="word",
                                      state="disabled", borderwidth=1)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("azul", foreground="#1A5FB4")
        self.log_text.tag_configure("ambar", foreground="#946800")
        self.log_text.tag_configure("vermelho", foreground="#C01C28")

    # ---------------- credenciais ----------------

    def _open_credentials(self) -> None:
        CredentialsDialog(self.root, on_saved=self._check_credenciais_banner)

    def _check_credenciais_banner(self) -> None:
        email, tem_senha = credenciais_atuais()
        if not email or not tem_senha:
            self.warning_label.configure(
                text='Credenciais do eLaw não configuradas — clique em "Credenciais" antes de executar.')
            self.warning_label.pack(fill="x", padx=24, before=self.paned)
        else:
            self.warning_label.pack_forget()

    # ---------------- lista de execuções ----------------

    def _refresh_index(self) -> None:
        self.runs = history.list_runs()
        self._populate_tree()
        self._update_run_now_state()
        if self.selected_run_id is None and self.runs:
            self._select_run(self.runs[0]["id"])
        elif self.selected_run_id is not None:
            self._render_detail(full=False)

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for r in self.runs:
            relatorios = ", ".join(r["downloads"].keys()) if r["downloads"] else "—"
            status = "running" if (r["id"] == self.live_run_id and self.live_running) else r["status"]
            label = RUN_STATUS_LABEL.get(status, status)
            categoria = RUN_STATUS_CATEGORIA.get(status, "cinza")
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                f"Execução #{r['id']}", fmt_data(r["started_at"]), relatorios, label), tags=(categoria,))
        if self.selected_run_id is not None and self.tree.exists(str(self.selected_run_id)):
            self.tree.selection_set(str(self.selected_run_id))

    def _on_tree_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        run_id = int(sel[0])
        if run_id == self.selected_run_id:
            return
        self.selected_run_id = run_id
        self._render_detail(full=True)

    def _select_run(self, run_id: int) -> None:
        self.selected_run_id = run_id
        if self.tree.exists(str(run_id)):
            self.tree.selection_set(str(run_id))
            self.tree.see(str(run_id))
        self._render_detail(full=True)

    def _get_selected_run_dict(self) -> Optional[dict]:
        if self.selected_run_id is None:
            return None
        for r in self.runs:
            if r["id"] == self.selected_run_id:
                return r
        return None

    def _update_run_now_state(self) -> None:
        self.run_now_btn.configure(state="disabled" if self.live_running else "normal")

    # ---------------- painel de detalhe ----------------

    def _render_detail(self, full: bool) -> None:
        run = self._get_selected_run_dict()
        if not run:
            self.detail_content.pack_forget()
            self.empty_label.pack(pady=40)
            return
        self.empty_label.pack_forget()
        self.detail_content.pack(fill="both", expand=True)

        live_view = self.selected_run_id == self.live_run_id
        is_running_now = live_view and self.live_running

        status = "running" if is_running_now else run["status"]
        label = RUN_STATUS_LABEL.get(status, status)
        categoria = RUN_STATUS_CATEGORIA.get(status, "cinza")

        self.detail_title_var.set(f"Execução #{run['id']}")
        self.detail_badge.configure(text=f"● {label}", foreground=CORES[categoria])

        meta = f"Iniciada em {fmt_data(run['started_at'])}"
        if run.get("finished_at"):
            meta += f" · Concluída em {fmt_data(run['finished_at'])}"
        self.detail_meta_var.set(meta)

        if (not live_view) and run.get("error"):
            self.error_var.set(run["error"])
            self.error_label.pack(anchor="w", pady=(4, 0), before=self.log_header)
        else:
            self.error_label.pack_forget()

        if is_running_now:
            self.cancel_btn.pack(side="left")
        else:
            self.cancel_btn.pack_forget()

        self._render_downloads_row(run)

        if full:
            self._reload_log_widget(run, live_view)

    def _render_downloads_row(self, run: Optional[dict]) -> None:
        """Um botão por relatório cuja URI (chave S3 completa) já está
        registrada no banco para essa execução (`run["downloads"]`) — nunca
        por uma checagem "ao vivo" no S3. Enquanto uma execução ainda está
        rodando, cada entrada é gravada assim que o relatório correspondente
        fica pronto (ver `_on_report`), não só no fim."""
        for widget in self.downloads_frame.winfo_children():
            widget.destroy()

        downloads: dict[str, str] = (run.get("downloads") or {}) if run else {}
        if not downloads:
            self.downloads_frame.pack_forget()
            return

        algum_botao = False
        for nome_relatorio, chave in downloads.items():
            ttk.Button(self.downloads_frame, text=f"📄 {nome_relatorio}",
                       command=lambda c=chave, n=nome_relatorio: self._baixar_e_abrir(c, n)).pack(side="left", padx=(0, 8))
            algum_botao = True

        if algum_botao:
            self.downloads_frame.pack(fill="x", pady=(10, 0), before=self.log_header)
        else:
            self.downloads_frame.pack_forget()

    def _baixar_e_abrir(self, chave: str, nome: str) -> None:
        """Baixa o relatório do S3 pra uma pasta temporária local e abre
        (ex.: no Excel) — roda numa thread de fundo, já que é uma chamada
        de rede, e só chama `os.startfile` de volta na thread principal."""
        self._flash_status(f"Baixando {nome}...", "azul")

        def trabalho() -> None:
            try:
                nome_arquivo = chave.rsplit("/", 1)[-1]
                destino = TEMP_DOWNLOADS_DIR / nome_arquivo
                storage.baixar_para_local(chave, destino)
                self.root.after(0, lambda: self._abrir_local_baixado(destino))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("Erro ao baixar", str(exc)))

        threading.Thread(target=trabalho, daemon=True).start()

    def _abrir_local_baixado(self, caminho: Path) -> None:
        os.startfile(str(caminho))
        self._flash_status("Relatório aberto.", "verde")

    # ---------------- log ----------------

    def _reload_log_widget(self, run: dict, live_view: bool) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if live_view:
            for t, l, m in self.live_log_lines:
                self._insert_log_line(t, l, m)
        else:
            log_path = LOGS_DIR / f"{run['id']}.log"
            if log_path.exists():
                for line in log_path.read_text(encoding="utf-8").splitlines():
                    parsed = _parse_log_line(line)
                    if parsed:
                        self._insert_log_line(*parsed)
                    elif line.strip():
                        self.log_text.insert("end", line + "\n")
            else:
                self.log_text.insert("end", "Log não encontrado para essa execução.\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _insert_log_line(self, time_str: str, level: str, message: str) -> None:
        tag = {"ERROR": "vermelho", "WARNING": "ambar"}.get(level, "azul")
        self.log_text.insert("end", f"{time_str}  ")
        self.log_text.insert("end", f"{level:<8}", (tag,))
        self.log_text.insert("end", f" {message}\n")

    def _append_log_line(self, time_str: str, level: str, message: str) -> None:
        # Só acompanha o final automaticamente se o usuário já estava lá —
        # rolar à força a cada linha nova atrapalharia quem parou pra ler
        # uma parte de cima do log durante uma execução longa.
        estava_no_fim = self.log_text.yview()[1] >= 0.999
        self.log_text.configure(state="normal")
        self._insert_log_line(time_str, level, message)
        if estava_no_fim:
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _copy_log(self) -> None:
        conteudo = self.log_text.get("1.0", "end")
        self.root.clipboard_clear()
        self.root.clipboard_append(conteudo)
        self._flash_status("Log copiado para a área de transferência.", "azul")

    def _abrir_log_arquivo(self) -> None:
        run = self._get_selected_run_dict()
        if not run:
            return
        log_path = LOGS_DIR / f"{run['id']}.log"
        if not log_path.exists():
            messagebox.showerror("Log não encontrado", "O arquivo de log dessa execução ainda não existe.")
            return
        os.startfile(str(log_path))

    # ---------------- executar / cancelar ----------------

    def _run_now(self) -> None:
        with self.run_lock:
            if self.live_running:
                return
            run_id = history.create_run_record()
            self.cancel_event = threading.Event()
            self.sessao = None
            self.live_run_id = run_id
            self.live_running = True
            self.live_steps = {}
            self.live_reports = {}
            self.live_log_lines = []

        self._flash_status("Execução iniciada.", "azul")
        self._refresh_index()
        self._select_run(run_id)
        self._update_run_now_state()

        thread = threading.Thread(target=self._run_pipeline, args=(run_id, self.cancel_event), daemon=True)
        thread.start()

    def _cancel_run(self) -> None:
        if not (self.live_running and self.selected_run_id == self.live_run_id):
            return
        if not messagebox.askyesno(
                "Cancelar execução",
                f"Cancelar a Execução #{self.live_run_id}? Isso interrompe tudo que estiver em andamento agora."):
            return
        logger.warning("Cancelamento solicitado para a execução #%d.", self.live_run_id)
        with self.run_lock:
            cancel_event = self.cancel_event
            sessao = self.sessao
        if cancel_event is not None:
            cancel_event.set()
        if sessao is not None:
            sessao.cancelar()
        self._flash_status("Cancelamento solicitado, aguarde a interrupção...", "ambar")

    def _run_pipeline(self, run_id: int, cancel_event: threading.Event) -> None:
        log_path = LOGS_DIR / f"{run_id}.log"
        handler = RunLogHandler(
            log_path, lambda t, l, m: self.root.after(0, self._on_log_line, run_id, t, l, m))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        def on_step(step_id: str, status: str, meta: Optional[str] = None) -> None:
            self.root.after(0, self._on_step, run_id, step_id, status, meta)

        def on_report(name: str, status: str, chave: Optional[str] = None) -> None:
            self.root.after(0, self._on_report, run_id, name, status, chave)

        def on_sessao(sessao: SessaoElaw) -> None:
            with self.run_lock:
                self.sessao = sessao

        error: Optional[str] = None
        cancelado = False
        downloads: dict[str, str] = {}
        try:
            downloads = executar(
                on_step=on_step, on_report=on_report,
                cancel_event=cancel_event, on_sessao=on_sessao,
            )
        except ExecucaoCancelada:
            cancelado = True
            logger.info("Execução #%d cancelada pelo usuário.", run_id)
        except Exception as exc:
            if cancel_event.is_set():
                # Navegador fechado à força pelo cancelamento — a exceção
                # que isso gera no Playwright varia, mas a causa é sempre essa.
                cancelado = True
                logger.info("Execução #%d cancelada pelo usuário.", run_id)
            else:
                error = str(exc)
                logger.exception("Execução #%d falhou", run_id)
        finally:
            root_logger.removeHandler(handler)
            handler.close()
            history.finish_run_record(run_id, error, downloads, cancelado=cancelado)
            self.root.after(0, self._on_run_finished, run_id, error, cancelado)

    # ---------------- callbacks (marcados na thread principal via after) ----------------

    def _on_step(self, run_id: int, step_id: str, status: str, meta: Optional[str]) -> None:
        if run_id != self.live_run_id:
            return
        self.live_steps[step_id] = {"status": status, "meta": meta}
        if self.selected_run_id == run_id:
            self._render_detail(full=False)

    def _on_report(self, run_id: int, name: str, status: str, chave: Optional[str] = None) -> None:
        if run_id != self.live_run_id:
            return
        self.live_reports[name] = status
        if status == "downloaded" and chave:
            # Grava no banco assim que o relatório fica pronto (não só no
            # fim da execução, como `finish_run_record`), pra liberar o
            # botão de download em tempo real — chamada de rede, roda numa
            # thread de fundo pra não travar a UI. O estado local
            # (self.runs) é atualizado desde já, sem esperar a escrita
            # terminar, pro botão aparecer imediatamente.
            threading.Thread(target=history.registrar_download, args=(run_id, name, chave), daemon=True).start()
            run = next((r for r in self.runs if r["id"] == run_id), None)
            if run is not None:
                run["downloads"][name] = chave
        if self.selected_run_id == run_id:
            self._render_detail(full=False)

    def _on_log_line(self, run_id: int, time_str: str, level: str, message: str) -> None:
        if run_id != self.live_run_id:
            return
        self.live_log_lines.append((time_str, level, message))
        if self.selected_run_id == run_id:
            self._append_log_line(time_str, level, message)

    def _on_run_finished(self, run_id: int, error: Optional[str], cancelado: bool) -> None:
        if run_id == self.live_run_id:
            self.live_running = False
        self._update_run_now_state()
        self._refresh_index()
        if self.selected_run_id == run_id:
            self._render_detail(full=False)

        texto = (f"Execução #{run_id} cancelada." if cancelado
                 else (f"Execução #{run_id} falhou." if error else f"Execução #{run_id} concluída."))
        categoria = "ambar" if cancelado else ("vermelho" if error else "verde")
        self._flash_status(texto, categoria)

    # ---------------- status transitório (equivalente ao "toast") ----------------

    def _flash_status(self, message: str, categoria: str = "azul") -> None:
        self.status_label.configure(text=message, foreground=CORES.get(categoria, CORES["cinza"]))
        if self._status_after_id:
            self.root.after_cancel(self._status_after_id)
        self._status_after_id = self.root.after(4200, lambda: self.status_label.configure(text=""))

    # ---------------- fechamento ----------------

    def _on_close(self) -> None:
        if self.live_running:
            if not messagebox.askyesno(
                    "Execução em andamento",
                    "Uma execução está em andamento. Fechar agora vai interrompê-la. Fechar mesmo assim?"):
                return
            with self.run_lock:
                cancel_event = self.cancel_event
                sessao = self.sessao
            if cancel_event is not None:
                cancel_event.set()
            if sessao is not None:
                sessao.cancelar()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
