"""Persistent application diagnostics. TRACE records calls into backend code."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


TRACE = 5
logging.addLevelName(TRACE, "TRACE")
LEVELS = {"OFF": 100, "ERROR": logging.ERROR, "WARNING": logging.WARNING,
          "INFO": logging.INFO, "DEBUG": logging.DEBUG, "TRACE": TRACE}
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = BACKEND_DIR.parent / "logs" / "app"
_trace_logger = logging.getLogger("app.calls")
_trace_prefix = str(BACKEND_DIR) + os.sep
_trace_self = str((BACKEND_DIR / "app_logging.py").resolve())
_filename_cache = {}
_configured_handlers = []
_trace_enabled = False
_previous_profile = None
_previous_thread_profile = None
_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
_current_session_id = "-"


@dataclass(frozen=True)
class AppLogConfig:
    level: str = "DEBUG"
    directory: Path = DEFAULT_LOG_DIR
    max_bytes: int = 10_000_000
    backups: int = 3
    keep_runs: int = 20


def config_from_env_and_argv(argv=None):
    """Read only our flags; the server parser handles the other CLI options."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--app-log-level", choices=LEVELS, default=os.getenv("MOBULA_LOG_LEVEL", "DEBUG").upper())
    parser.add_argument("--app-log-dir", default=os.getenv("MOBULA_LOG_DIR", str(DEFAULT_LOG_DIR)))
    parser.add_argument("--app-log-max-bytes", type=int, default=int(os.getenv("MOBULA_LOG_MAX_BYTES", "10000000")))
    parser.add_argument("--app-log-backups", type=int, default=int(os.getenv("MOBULA_LOG_BACKUPS", "3")))
    parser.add_argument("--app-log-keep-runs", type=int, default=int(os.getenv("MOBULA_LOG_KEEP_RUNS", "20")))
    args, _ = parser.parse_known_args(argv)
    if args.app_log_level not in LEVELS:
        parser.error("Nivel de log inválido")
    if args.app_log_max_bytes <= 0 or args.app_log_backups < 1 or args.app_log_keep_runs < 1:
        parser.error("max-bytes, backups y keep-runs deben ser positivos")
    return AppLogConfig(args.app_log_level, Path(args.app_log_dir), args.app_log_max_bytes,
                        args.app_log_backups, args.app_log_keep_runs)


class UTCFormatter(logging.Formatter):
    converter = staticmethod(lambda timestamp: datetime.fromtimestamp(timestamp, timezone.utc).timetuple())


def _profile(frame, event, arg):
    if event != "call":
        return
    code = frame.f_code
    filename = code.co_filename
    if filename not in _filename_cache:
        absolute = os.path.abspath(filename)
        _filename_cache[filename] = (absolute[len(_trace_prefix):]
                                     if absolute.startswith(_trace_prefix) and absolute != _trace_self else None)
    relative = _filename_cache[filename]
    if relative is not None:
        _trace_logger.log(TRACE, "CALL %s:%s %s", relative,
                          code.co_firstlineno, code.co_qualname)


def configure_logging(config):
    """Replace our handlers and tracing without touching unrelated handlers."""
    global _trace_enabled, _previous_profile, _previous_thread_profile
    root = logging.getLogger()
    if _trace_enabled:
        sys.setprofile(_previous_profile)
        threading.setprofile(_previous_thread_profile)
        _trace_enabled = False
    for handler in _configured_handlers:
        root.removeHandler(handler)
        handler.close()
    _configured_handlers.clear()

    root.setLevel(LEVELS[config.level])
    if config.level == "OFF":
        return None

    config.directory.mkdir(parents=True, exist_ok=True)
    path = config.directory / f"app_{_run_id}_{os.getpid()}.log"
    handler = RotatingFileHandler(path, maxBytes=config.max_bytes,
                                  backupCount=config.backups, encoding="utf-8")
    handler.setFormatter(UTCFormatter("%(asctime)sZ %(levelname)s run=%(run_id)s session=%(session_id)s "
                                      "pid=%(process)d thread=%(threadName)s "
                                      "%(name)s: %(message)s"))
    # A filter attaches the same run ID to records from our modules and libraries.
    def context_filter(record):
        record.run_id = _run_id
        record.session_id = _current_session_id
        return True
    handler.addFilter(context_filter)
    root.addHandler(handler)
    _configured_handlers.append(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    _configured_handlers.append(console)
    old_runs = sorted((item for item in config.directory.glob("app_*.log") if item != path),
                      key=lambda item: item.stat().st_mtime, reverse=True)
    for old in old_runs[max(0, config.keep_runs - 1):]:
        for artifact in [old, *old.parent.glob(old.name + ".*")]:
            artifact.unlink(missing_ok=True)
    if config.level == "TRACE":
        _previous_profile = sys.getprofile()
        _previous_thread_profile = threading.getprofile()
        sys.setprofile(_profile)
        threading.setprofile(_profile)
        _trace_enabled = True
    logging.getLogger("app").info("Logging iniciado level=%s file=%s", config.level, path)
    return path


def run_id():
    return _run_id


def set_session_id(value):
    global _current_session_id
    _current_session_id = value or "-"
