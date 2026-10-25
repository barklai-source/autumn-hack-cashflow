"""Mask company identifiers and counterparty names in server-side log records."""

from __future__ import annotations

import logging
import re


class SensitiveLogFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self._sensitive_names: tuple[str, ...] = ()

    def update_dataset(self, dataset) -> None:
        names: set[str] = set()
        for frame, column in (
            (dataset.companies, "name"),
            (dataset.operations, "counterparty_name"),
        ):
            if column in frame:
                names.update(
                    str(value).strip()
                    for value in frame[column].dropna().unique()
                    if len(str(value).strip()) >= 3
                )
        self._sensitive_names = tuple(sorted(names, key=len, reverse=True))

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        message = re.sub(r"(?<!\d)(?:\d[ -]?){9}\d(?:[ -]?\d{2})?(?!\d)", "[ИНН СКРЫТ]", message)
        for name in self._sensitive_names:
            message = re.sub(re.escape(name), "[КОНТРАГЕНТ СКРЫТ]", message, flags=re.IGNORECASE)
        record.msg = message
        record.args = ()
        return True


_FILTER = SensitiveLogFilter()


def configure_sensitive_logging(dataset) -> None:
    """Install one filter on configured handlers and refresh sensitive values."""
    _FILTER.update_dataset(dataset)
    root_logger = logging.getLogger()
    configured_loggers = [root_logger, *(
        logger
        for logger in logging.root.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )]
    for configured_logger in configured_loggers:
        for handler in configured_logger.handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)
