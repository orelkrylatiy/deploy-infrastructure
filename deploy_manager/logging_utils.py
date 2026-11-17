from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_ROOT = Path("/var/log/deploy-manager")


def get_logger(project: str) -> logging.Logger:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"deploy_manager.{project}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        file_handler = RotatingFileHandler(
            LOG_ROOT / f"{project}.log", maxBytes=5 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(stream)
        logger.addHandler(file_handler)
    return logger
