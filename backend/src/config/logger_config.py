import logging
from logging.handlers import TimedRotatingFileHandler, QueueHandler, QueueListener
import queue
import uuid
import os
from datetime import datetime
from threading import Lock
import socket
from fastapi import WebSocket
import contextvars
from typing import Optional

from backend.src.constants import log_constants
from backend.src.config.app_settings import settings

trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
request_info_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_info", default=None)


class TraceIDFilter(logging.Filter):
    def __init__(self):
        super().__init__()

    def filter(self, record):
        trace_id = trace_id_var.get()
        request_info = request_info_var.get()
        record.trace_id = trace_id
        record.request_info = request_info
        return True


trace_id_filter = TraceIDFilter()


class CustomFormatter(logging.Formatter):
    def format(self, record):
        record.file_name = getattr(record, "filename", "")
        record.ppid = getattr(record, "ppid", os.getppid())
        record.pid = getattr(record, "pid", os.getpid())
        record.trace_id = getattr(record, "trace_id", "-")
        record.request_info = getattr(record, "request_info", "-")
        return super().format(record)


class CustomTimedRotatingFileHandler(TimedRotatingFileHandler):
    _rollover_lock = Lock()

    def __init__(self, filename, when="h", interval=1, backupCount=0,
                 encoding=None, delay=False, utc=False, atTime=None):
        self.original_filename = filename
        self.suffix_format = self._get_suffix_format(when)
        self.current_date = datetime.now().strftime(self.suffix_format)
        folder_path = self._create_folder_for_current_day()
        super().__init__(
            self._construct_filename(folder_path), when, interval,
            backupCount, encoding, delay, utc, atTime,
        )
        self.baseFilename = self._construct_filename(folder_path)

    def _get_suffix_format(self, when):
        formats = {
            "D": "%Y-%m-%d",
            "H": "%Y-%m-%d_%H",
            "M": "%Y-%m-%d_%H-%M",
            "S": "%Y-%m-%d_%H-%M-%S",
        }
        if when.upper() not in formats:
            raise ValueError("Invalid value for 'when'. Use 'D', 'H', 'M', or 'S'.")
        return formats[when.upper()]

    def _create_folder_for_current_day(self):
        current_day_folder = datetime.now().strftime("%Y-%m-%d")
        folder_path = os.path.join(
            os.path.dirname(log_constants.LOG_FILE_PATH), current_day_folder
        )
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def _construct_filename(self, folder_path):
        ext = ".log"
        new_filename = f"{self.original_filename}_{self.current_date}{ext}"
        return os.path.join(folder_path, new_filename)

    def doRollover(self):
        with self._rollover_lock:
            if self.stream:
                self.stream.close()
                self.stream = None  # type: ignore[assignment]
            self.current_date = datetime.now().strftime(self.suffix_format)
            folder_path = self._create_folder_for_current_day()
            self.baseFilename = self._construct_filename(folder_path)
            self.stream = self._open()

    def emit(self, record):
        try:
            if self.shouldRollover(record):
                self.doRollover()
            super(TimedRotatingFileHandler, self).emit(record)
        except Exception:
            self.handleError(record)


def get_ip_address():
    try:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
    except socket.gaierror:
        ip_address = "127.0.0.1"
    return ip_address


def add_trace_id(request):
    trace_id = str(uuid.uuid4())
    request_info = f"{request.client.host} - {request.method} {request.url.path}"
    request.state.trace_id = trace_id
    request.state.request_info = request_info
    trace_id_var.set(trace_id)
    request_info_var.set(request_info)


def add_trace_id_ws(websocket: WebSocket):
    trace_id = str(uuid.uuid4())
    client_host = websocket.client.host if websocket.client else "Unknown"
    request_info = f"{client_host} - WebSocket"
    trace_id_var.set(trace_id)
    request_info_var.set(request_info)


_debug = settings.LOGGER_DEBUG_FLAG.upper() == "Y"
_file_logging_enabled = not settings.is_production

# Stdout handler — always active so logs appear in Render's dashboard and local terminal
_stdout_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
_stdout_handler = logging.StreamHandler()
_stdout_handler.setFormatter(_stdout_formatter)

if _file_logging_enabled:
    formatter = CustomFormatter(
        "%(asctime)s - %(levelname)s - [PPID-%(ppid)s] - [PID-%(pid)s] - "
        "%(trace_id)s - %(file_name)s - %(request_info)s - %(message)s"
    )

    error_logger_filename = f"{get_ip_address()}{log_constants.ERROR_INITIAL_FILE_NAME}"
    error_handler = CustomTimedRotatingFileHandler(filename=error_logger_filename, when="H", encoding="utf-8")
    error_handler.setFormatter(formatter)

    req_res_logger_filename = f"{get_ip_address()}{log_constants.INQ_REQ_RESP_INITIAL_FILE_NAME}"
    req_res_handler = CustomTimedRotatingFileHandler(filename=req_res_logger_filename, when="H", encoding="utf-8")
    req_res_handler.setFormatter(formatter)

    access_logger_filename = f"{get_ip_address()}{log_constants.ACCESS_FILE_NAME}"
    access_log_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    access_log_handler = CustomTimedRotatingFileHandler(filename=access_logger_filename, when="D", encoding="utf-8")
    access_log_handler.setFormatter(access_log_format)

    application_log_filename = f"{get_ip_address()}{log_constants.APPLICATION_FILE_NAME}"
    application_log_format = logging.Formatter("%(asctime)s-%(process)d-%(levelname)s-%(message)s")
    application_log_handler = CustomTimedRotatingFileHandler(filename=application_log_filename, when="H", encoding="utf-8")
    application_log_handler.setFormatter(application_log_format)

    # Async queue handlers
    error_log_queue = queue.Queue(-1)
    req_res_log_queue = queue.Queue(-1)
    access_log_queue = queue.Queue(-1)
    application_log_queue = queue.Queue(-1)

    error_queue_handler = QueueHandler(error_log_queue)
    req_res_queue_handler = QueueHandler(req_res_log_queue)
    access_queue_handler = QueueHandler(access_log_queue)
    application_queue_handler = QueueHandler(application_log_queue)

    error_queue_listener = QueueListener(error_log_queue, error_handler)
    req_res_queue_listener = QueueListener(req_res_log_queue, req_res_handler)
    access_queue_listener = QueueListener(access_log_queue, access_log_handler)
    application_queue_listener = QueueListener(application_log_queue, application_log_handler)


def _make_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers = []
    logger.setLevel(logging.DEBUG if _debug else logging.INFO)
    logger.addHandler(_stdout_handler)
    logger.addFilter(trace_id_filter)
    logger.propagate = False
    return logger


error_logger = _make_logger("error_logger")
req_res_logger = _make_logger("req_res_logger")
access_logger = _make_logger("access_logger")
application_logger = _make_logger("application_logger")

if _file_logging_enabled:
    error_logger.addHandler(error_queue_handler)
    req_res_logger.addHandler(req_res_queue_handler)
    access_logger.addHandler(access_queue_handler)
    application_logger.addHandler(application_queue_handler)


def log_response(data) -> None:
    req_res_logger.info("Response Data: %s", data)


def access_log(request, response, response_time):
    access_logger.info(
        f"{request.client.host} - - {request.client.port} "
        f"[{datetime.now().strftime('%d/%b/%Y:%H:%M:%S %z')}] "
        f'"{request.method} {request.url.path} HTTP/1.1" {response.status_code} '
        f"{response_time:.6f}"
    )


def start_logging_listener():
    if not _file_logging_enabled:
        return
    error_queue_listener.start()
    req_res_queue_listener.start()
    access_queue_listener.start()
    application_queue_listener.start()


def stop_logging_listener():
    if not _file_logging_enabled:
        return
    error_queue_listener.stop()
    req_res_queue_listener.stop()
    access_queue_listener.stop()
    application_queue_listener.stop()
