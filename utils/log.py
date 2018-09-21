import sys
import logging
import traceback
from conf import conf

LOGGING_CONFIG = dict(
    version=1,
    disable_existing_loggers=False,

    loggers={
        "app": {
            "level": "INFO" if conf.IS_PROD else "DEBUG",
            "handlers": ["console"]
        },
        "root": {
            "level": "INFO",
            "handlers": []
        },
        "sanic.error": {
            "level": "INFO",
            "handlers": [],
            "propagate": False,
            "qualname": "sanic.error"
        }
        # "sanic.access": {
        #     "level": "INFO",
        #     "handlers": ["access_console"],
        #     "propagate": False,
        #     "qualname": "sanic.access"
        # }
    },
    handlers={
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": sys.stdout
        }
        # "access_console": {
        #     "class": "logging.StreamHandler",
        #     "formatter": "access",
        #     "stream": sys.stdout
        # }
    },
    formatters={
        "generic": {
            "format": "%(asctime)s - (%(name)s) [%(levelname)s] %(process)d %(filename)s:%(lineno)d | %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter"
        }
        # "access": {
        #     "format": "%(asctime)s - (%(name)s)[%(levelname)s][%(host)s]: " +
        #               "%(request)s %(message)s %(status)d %(byte)d",
        #     "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
        #     "class": "logging.Formatter"
        # }
    }
)

logger = logging.getLogger('app')

def print_excp(e: Exception):
    tb = traceback.format_tb(e.__traceback__, 20)
    logger.error(str(e) + '\n' + ''.join(tb))
