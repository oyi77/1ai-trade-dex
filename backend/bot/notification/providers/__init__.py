import importlib
import logging
import os

logger = logging.getLogger(__name__)

providers_dir = os.path.dirname(__file__)
for _, name, _ in os.walk(providers_dir):
    if name != "providers":
        continue
    for filename in os.listdir(providers_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            module_name = filename[:-3]
            try:
                module = importlib.import_module(f"backend.bot.notification.providers.{module_name}")
            except Exception:
                logger.warning("Failed to import notification provider '%s'", module_name, exc_info=True)
