"""Serviço web (FastAPI) que expõe o pipeline de relatórios via HTTP/WebSocket,
mantém histórico de execuções em SQLite e permite agendá-lo via APScheduler."""

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from main import executar
from modules.elaw import BASE_REPORTS_DIR, limpar_relatorios_antigos

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "runs.db"
LOGS_DIR = BASE_DIR / "logs" / "runs"
SCHEDULE_FILE = BASE_DIR / "schedule.json"
DAY_IDS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

LOGS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

# ---------------------------------------------------------------------------
# Estado em memória da execução atual + WebSocket clients
# ---------------------------------------------------------------------------

state_lock = threading.Lock()
run_lock = threading.Lock()
run_state = {"running": False, "run_id": None, "steps": {}, "reports": {}}

ws_clients: set[WebSocket] = set()
main_loop: Optional[asyncio.AbstractEventLoop] = None

scheduler = BackgroundScheduler()


async def broadcast(message: dict) -> None:
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


def broadcast_threadsafe(message: dict) -> None:
    if main_loop is None:
        return
    asyncio.run_coroutine_threadsafe(broadcast(message), main_loop)


def status_snapshot() -> dict:
    with state_lock:
        return {
            "type": "status",
            "running": run_state["running"],
            "run_id": run_state["run_id"],
            "steps": dict(run_state["steps"]),
            "reports": dict(run_state["reports"]),
        }


# ---------------------------------------------------------------------------
# Persistência do histórico (SQLite)
# ---------------------------------------------------------------------------

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                downloads TEXT NOT NULL DEFAULT '[]',
                download_dir TEXT,
                error TEXT
            )
        """)
        colunas = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
        if "download_dir" not in colunas:
            conn.execute("ALTER TABLE runs ADD COLUMN download_dir TEXT")
        conn.commit()


def create_run_record() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, downloads) VALUES (?, 'running', '[]')",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        return cur.lastrowid


def finish_run_record(run_id: int, error: Optional[str], download_dir: Optional[str], downloads: list[str]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, downloads = ?, download_dir = ?, error = ? WHERE id = ?",
            (
                datetime.now().isoformat(timespec="seconds"),
                "error" if error else "success",
                json.dumps(downloads),
                download_dir,
                error,
                run_id,
            ),
        )
        conn.commit()


def list_runs(limit: int = 200) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, started_at, finished_at, status, downloads, download_dir, error FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        runs = []
        for row in rows:
            run = dict(row)
            try:
                run["downloads"] = json.loads(run["downloads"]) if run["downloads"] else []
            except json.JSONDecodeError:
                run["downloads"] = []
            runs.append(run)
        return runs


def get_run(run_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, downloads, download_dir FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        run = dict(row)
        try:
            run["downloads"] = json.loads(run["downloads"]) if run["downloads"] else []
        except json.JSONDecodeError:
            run["downloads"] = []
        return run


# ---------------------------------------------------------------------------
# Execução do pipeline em thread separada (Playwright é síncrono)
# ---------------------------------------------------------------------------

class RunLogHandler(logging.Handler):
    """Grava cada linha de log no arquivo da run e retransmite via WebSocket."""

    def __init__(self, log_path: Path):
        super().__init__()
        self.file = open(log_path, "a", encoding="utf-8")
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted = self.format(record)
            self.file.write(formatted + "\n")
            self.file.flush()
            broadcast_threadsafe({
                "type": "log",
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": record.getMessage(),
            })
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.file.close()
        finally:
            super().close()


def _executar_run(run_id: int) -> None:
    log_path = LOGS_DIR / f"{run_id}.log"
    handler = RunLogHandler(log_path)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    def on_step(step_id: str, status: str, meta: Optional[str] = None) -> None:
        with state_lock:
            run_state["steps"][step_id] = {"status": status, "meta": meta}
        broadcast_threadsafe({"type": "step", "step": step_id, "status": status, "meta": meta})

    def on_report(name: str, status: str) -> None:
        with state_lock:
            run_state["reports"][name] = status
        broadcast_threadsafe({"type": "report", "name": name, "status": status})

    error: Optional[str] = None
    downloads: list[str] = []
    download_dir: Optional[str] = None
    try:
        paths = executar(on_step=on_step, on_report=on_report)
        downloads = [p.name for p in paths]
        if paths:
            download_dir = paths[0].parent.name
    except Exception as exc:
        error = str(exc)
        logger.exception("Execução #%d falhou", run_id)
    finally:
        root_logger.removeHandler(handler)
        handler.close()
        with state_lock:
            run_state["running"] = False
        finish_run_record(run_id, error, download_dir, downloads)
        snapshot = status_snapshot()
        snapshot["type"] = "run_finished"
        snapshot["error"] = error
        broadcast_threadsafe(snapshot)


def iniciar_execucao() -> bool:
    """Dispara uma nova execução em thread separada. Retorna False se já
    houver uma execução em andamento (não sobrepõe runs)."""
    with run_lock:
        with state_lock:
            if run_state["running"]:
                return False
            run_state["running"] = True
            run_state["steps"] = {}
            run_state["reports"] = {}
        run_id = create_run_record()
        with state_lock:
            run_state["run_id"] = run_id

    thread = threading.Thread(target=_executar_run, args=(run_id,), daemon=True)
    thread.start()
    return True


# ---------------------------------------------------------------------------
# Agendamento (APScheduler + schedule.json)
# ---------------------------------------------------------------------------

def load_schedule_config() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("schedule.json inválido, usando configuração padrão.")
    return {"enabled": False, "hour": 8, "minute": 0, "days": []}


def save_schedule_config(cfg: dict) -> None:
    SCHEDULE_FILE.write_text(json.dumps(cfg), encoding="utf-8")


def apply_schedule(cfg: dict) -> None:
    try:
        scheduler.remove_job("pipeline_schedule")
    except JobLookupError:
        pass
    if cfg["enabled"] and cfg["days"]:
        trigger = CronTrigger(day_of_week=",".join(cfg["days"]), hour=cfg["hour"], minute=cfg["minute"])
        scheduler.add_job(iniciar_execucao, trigger, id="pipeline_schedule", replace_existing=True)


def schedule_next_run_time() -> Optional[str]:
    job = scheduler.get_job("pipeline_schedule")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


class ScheduleUpdate(BaseModel):
    enabled: bool
    hour: int
    minute: int
    days: list[str]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup() -> None:
    global main_loop
    main_loop = asyncio.get_running_loop()
    init_db()
    limpar_relatorios_antigos()
    scheduler.start()
    apply_schedule(load_schedule_config())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/status")
async def api_status() -> dict:
    return status_snapshot()


@app.post("/api/run")
async def api_run() -> JSONResponse:
    if not iniciar_execucao():
        return JSONResponse({"error": "Já existe uma execução em andamento."}, status_code=409)
    return {"status": "started"}


@app.get("/api/history")
async def api_history() -> list[dict]:
    return list_runs()


@app.get("/api/history/{run_id}/logs")
async def api_history_logs(run_id: int) -> dict:
    log_path = LOGS_DIR / f"{run_id}.log"
    if not log_path.exists():
        return {"error": "Log não encontrado para essa execução."}
    return {"log": log_path.read_text(encoding="utf-8")}


@app.get("/api/history/{run_id}/download/{filename}")
async def api_history_download(run_id: int, filename: str):
    run = get_run(run_id)
    if run is None or not run["download_dir"] or filename not in run["downloads"]:
        return JSONResponse({"error": "Arquivo não encontrado para essa execução."}, status_code=404)

    file_path = BASE_REPORTS_DIR / run["download_dir"] / filename
    if not file_path.is_file():
        return JSONResponse({"error": "Arquivo não existe mais (pode ter expirado)."}, status_code=404)

    return FileResponse(file_path, filename=filename)


@app.get("/api/schedule")
async def api_get_schedule() -> dict:
    cfg = load_schedule_config()
    cfg["next_run_time"] = schedule_next_run_time()
    return cfg


@app.post("/api/schedule")
async def api_set_schedule(update: ScheduleUpdate) -> JSONResponse:
    invalid_days = [d for d in update.days if d not in DAY_IDS]
    if invalid_days:
        return JSONResponse({"error": f"Dias inválidos: {invalid_days}"}, status_code=400)
    if update.enabled and not update.days:
        return JSONResponse({"error": "Selecione ao menos um dia da semana."}, status_code=400)
    if not (0 <= update.hour <= 23 and 0 <= update.minute <= 59):
        return JSONResponse({"error": "Horário inválido."}, status_code=400)

    cfg = {"enabled": update.enabled, "hour": update.hour, "minute": update.minute, "days": update.days}
    save_schedule_config(cfg)
    apply_schedule(cfg)
    cfg["next_run_time"] = schedule_next_run_time()
    return cfg


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        await websocket.send_json(status_snapshot())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
