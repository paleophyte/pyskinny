import logging


MESSAGE_LOG_LEVEL = logging.WARNING - 5
_VERBOSE_COUNT = 0


def verbose_count() -> int:
    return _VERBOSE_COUNT


def skinny_trace_enabled() -> bool:
    """True at -vvvv and above: log every Skinny SEND/RECV."""
    return _VERBOSE_COUNT >= 4


def log_skinny_wire(
    logger: logging.Logger,
    device: str,
    direction: str,
    msg_id: int,
    name: str,
    nbytes: int = 0,
) -> None:
    """Log one Skinny frame at MESSAGE level when -vvvv wire trace is enabled."""
    if not skinny_trace_enabled():
        return
    ensure_message_log_level()
    logger.log(
        MESSAGE_LOG_LEVEL,
        "(%s) [%s] 0x%04X %s (%d bytes)",
        device,
        direction,
        msg_id,
        name,
        nbytes,
    )


def addLoggingLevel(levelName, levelNum, methodName=None):
    """
    Comprehensively adds a new logging level to the `logging` module and the
    currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    To avoid accidental clobberings of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    Example
    -------
    >>> addLoggingLevel('TRACE', logging.DEBUG - 5)
    >>> logging.getLogger(__name__).setLevel("TRACE")
    >>> logging.getLogger(__name__).trace('that worked')
    >>> logging.trace('so did this')
    >>> logging.TRACE
    5

    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
       raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
       raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
       raise AttributeError('{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)
    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


def ensure_message_log_level():
    """Register the custom MESSAGE level once per process."""
    try:
        addLoggingLevel("MESSAGE", MESSAGE_LOG_LEVEL, methodName="message")
    except AttributeError:
        pass


def log_level_from_verbose(verbose: int) -> int:
    verbosity = min(int(verbose), 4)
    levels = [logging.WARNING, MESSAGE_LOG_LEVEL, logging.INFO, logging.DEBUG]
    return levels[verbosity - 1 if verbosity > 0 else 0]


def configure_logging_from_verbose(
    verbose: int,
    *,
    fmt: str | None = None,
    tftpy_level: int = logging.WARNING,
) -> int:
    """Configure root logging from -v / -vv / -vvv / -vvvv style counts."""
    global _VERBOSE_COUNT
    _VERBOSE_COUNT = max(0, int(verbose))
    ensure_message_log_level()
    log_level = log_level_from_verbose(verbose)
    if fmt is None:
        fmt = "%(asctime)s [%(levelname)-7s] %(name)-22s: %(message)s"
    logging.basicConfig(level=log_level, format=fmt, force=True)
    logging.getLogger("tftpy").setLevel(tftpy_level)
    from utils.tftp_logging import configure_tftpy_logging

    configure_tftpy_logging(level=tftpy_level)
    return log_level
