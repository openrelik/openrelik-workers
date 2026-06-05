import freezegun
import logging
import os
from openrelik_worker_common.logging import Logger
import pytest_structlog


# Log usage functions
def log_plain():
    os.environ.pop("OPENRELIK_LOG_TYPE", None)
    logger = Logger().get_logger(__name__)
    logger.info("test")


def log_wrap():
    os.environ.pop("OPENRELIK_LOG_TYPE", None)
    logger = Logger().get_logger(name=__name__, wrap_logger=logging.getLogger())
    logger.info("test")


def log_bind_structlog():
    os.environ["OPENRELIK_LOG_TYPE"] = "structlog"
    log = Logger()
    logger = log.get_logger(__name__)
    log.bind(workflow_id=12345)
    logger.info("test")


def log_structlog():
    os.environ["OPENRELIK_LOG_TYPE"] = "structlog"
    logger = Logger().get_logger(__name__)
    logger.info("test")


def log_bind_structlog_console():
    os.environ["OPENRELIK_LOG_TYPE"] = "structlog_console"
    log = Logger()
    logger = log.get_logger(__name__)
    log.bind(workflow_id=12345)
    logger.info("test")


def log_structlog_console():
    os.environ["OPENRELIK_LOG_TYPE"] = "structlog_console"
    logger = Logger().get_logger(__name__)
    logger.info("test")


# Tests
def test_structlog(log: pytest_structlog.StructuredLogCapture):
    log_structlog()
    assert log.has("test", level="info")
    assert not log.has("bla", workflow_id=12345)


def test_bind_structlog(log: pytest_structlog.StructuredLogCapture):
    log_bind_structlog()
    assert log.has("test", level="info", workflow_id=12345)


@freezegun.freeze_time("2025-01-01T00:00:00.000000Z")
def test_structlog_console(caplog):
    caplog.set_level(logging.INFO)
    log_structlog_console()
    assert (
        "INFO     tests.test_logging:test_logging.py:46 2025-01-01T00:00:00Z [info     ] test                           [tests.test_logging] filename=test_logging.py func_name=log_structlog_console lineno=46\n"
        == caplog.text
    )


@freezegun.freeze_time("2025-01-01T00:00:00.000000Z")
def test_bind_structlog_console(caplog):
    caplog.set_level(logging.INFO)
    log_bind_structlog_console()
    assert (
        "INFO     tests.test_logging:test_logging.py:40 2025-01-01T00:00:00Z [info     ] test                           [tests.test_logging] filename=test_logging.py func_name=log_bind_structlog_console lineno=40 workflow_id=12345\n"
        == caplog.text
    )


def test_get_plain_python(caplog):
    caplog.set_level(logging.INFO)
    log_plain()
    assert "INFO     tests.test_logging:test_logging.py:12 test\n" == caplog.text


def test_get_wrap(log: pytest_structlog.StructuredLogCapture):
    log_wrap()
    assert log.has("test", level="info")
