"""Persistence and configurable tracing without hardware dependencies."""

import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app_logging import AppLogConfig, config_from_env_and_argv, configure_logging
import session_manager


class AppLoggingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.original_level = logging.getLogger().level
        self.original_profile = sys.getprofile()
        self.addCleanup(self._restore_logging)

    def _restore_logging(self):
        configure_logging(AppLogConfig(level="OFF", directory=self.path))
        logging.getLogger().setLevel(self.original_level)

    def test_default_and_environment_override(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config_from_env_and_argv([]).level, "DEBUG")
        with patch.dict("os.environ", {"MOBULA_LOG_LEVEL": "warning"}, clear=True):
            self.assertEqual(config_from_env_and_argv([]).level, "WARNING")
            self.assertEqual(config_from_env_and_argv(["--app-log-level", "TRACE"]).level, "TRACE")

    def test_off_creates_no_file_and_debug_rotates(self):
        self.assertIsNone(configure_logging(AppLogConfig(level="OFF", directory=self.path)))
        self.assertEqual(list(self.path.iterdir()), [])
        path = configure_logging(AppLogConfig(level="DEBUG", directory=self.path,
                                              max_bytes=512, backups=2))
        for _ in range(40):
            logging.getLogger("test").debug("A" * 80)
        self.assertTrue(path.exists())
        self.assertTrue(path.with_name(path.name + ".1").exists())
        self.assertLessEqual(path.stat().st_size, 512)

    def test_trace_records_backend_function_calls_without_arguments(self):
        path = configure_logging(AppLogConfig(level="TRACE", directory=self.path,
                                              max_bytes=100_000, backups=1))
        with patch.object(session_manager, "LOGS_DIR", self.path):
            session = session_manager.SessionManager()
            worker = threading.Thread(name="worker-test", target=lambda: session.save(finalize=False))
            worker.start()
            worker.join()
        configure_logging(AppLogConfig(level="OFF", directory=self.path))
        self.assertIs(sys.getprofile(), self.original_profile)
        content = path.read_text()
        self.assertIn("CALL session_manager.py", content)
        self.assertIn("SessionManager.save", content)
        self.assertIn("thread=worker-test", content)
        self.assertIn("run=", content)
        self.assertIn("session=", content)
        self.assertIn("Z TRACE", content)

    def test_empty_session_has_atomic_checkpoint_and_final_state(self):
        with patch.object(session_manager, "LOGS_DIR", self.path):
            session = session_manager.SessionManager()
            output = Path(session.save(finalize=False))
            data = json.loads(output.read_text())
            self.assertEqual(data["frames"], [])
            self.assertTrue(data["live"])
            self.assertIsNone(data["end_time"])
            self.assertFalse(output.with_suffix(".tmp").exists())
            session.save()
            final = json.loads(output.read_text())
            self.assertFalse(final["live"])
            self.assertIsNotNone(final["end_time"])
            session.save(finalize=False)
            self.assertFalse(json.loads(output.read_text())["live"])


if __name__ == "__main__":
    unittest.main()
