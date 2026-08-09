"""Per-run file logging for ammeter test executions.

Each :class:`TestLogger` owns a private :class:`logging.Logger` and a single
file handler writing to a uniquely named, timestamped file. Owning a private
logger avoids the duplicate-handler / duplicate-line problem that arises when
several runs share a logger obtained by name. Filenames and record timestamps
use local time so they read naturally to whoever is running the bench.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from itertools import count
from pathlib import Path

DEFAULT_LOG_DIRECTORY = "results/logs"

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Guarantees a distinct logger name (and therefore a distinct file) even when
# two loggers with the same test name are created within the same UTC second.
_instance_counter = count(1)


class TestLogger:
    """Write DEBUG-level records for one test run to a dedicated log file."""

    def __init__(
        self,
        test_name: str,
        *,
        log_directory: str | os.PathLike[str] = DEFAULT_LOG_DIRECTORY,
    ) -> None:
        if not isinstance(test_name, str) or not test_name.strip():
            raise ValueError("test_name must be a non-empty string")
        self._test_name = test_name.strip()
        self._log_directory = Path(log_directory)
        self.log_file = self._resolve_log_file()
        self.logger = self._setup_logger()

    @property
    def test_name(self) -> str:
        return self._test_name

    def _resolve_log_file(self) -> Path:
        """Create the log directory and return a unique, timestamped path."""

        self._log_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        instance_id = next(_instance_counter)
        safe_name = "".join(
            character if character.isalnum() or character in ("-", "_") else "_"
            for character in self._test_name
        )
        return self._log_directory / f"{timestamp}_{safe_name}_{instance_id}.log"

    def _setup_logger(self) -> logging.Logger:
        """Configure a private logger with exactly one file handler."""

        logger = logging.getLogger(f"ammeter.test.{self.log_file.stem}")
        logger.setLevel(logging.DEBUG)
        # Keep records out of the root logger so demo stdout stays clean and
        # records are never emitted twice.
        logger.propagate = False
        if not logger.handlers:
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
            logger.addHandler(file_handler)
        return logger

    def info(self, message: str) -> None:
        self.logger.info(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def debug(self, message: str) -> None:
        self.logger.debug(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def close(self) -> None:
        """Flush and release the file handler; safe to call more than once."""

        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)

    def __enter__(self) -> "TestLogger":
        return self

    def __exit__(self, *_exception_details: object) -> None:
        self.close()
