"""Register all handlers with the Telegram Application.

Handler modules are imported lazily. Modules that haven't been converted from
Slack to Telegram yet will log a warning and be skipped gracefully.
"""
import logging

from telegram.ext import Application

logger = logging.getLogger(__name__)

# Handler modules in registration order.
# Each module must expose a register(application: Application) function.
_HANDLER_MODULES = ["capture", "commands", "actions", "feedback", "dashboard"]


def register_all(application: Application):
    """Register all event listeners, commands, and callback query handlers."""
    for module_name in _HANDLER_MODULES:
        try:
            module = __import__(f"handlers.{module_name}", fromlist=["register"])
            module.register(application)
            logger.info("Registered handler module: %s", module_name)
        except ImportError as e:
            logger.warning("Handler module %s not available: %s", module_name, e)
        except AttributeError:
            logger.warning("Handler module %s has no register() function", module_name)
        except Exception as e:
            logger.warning("Failed to register handler module %s: %s", module_name, e)
