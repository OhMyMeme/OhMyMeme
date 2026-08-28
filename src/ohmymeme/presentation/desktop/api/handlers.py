"""Compatibility exports for desktop bridge handlers."""

from .import_handler import ImportHandler
from .meme_handler import MemeHandler
from .sync_handler import SyncHandler
from .update_handler import UpdateHandler
from .window_settings_handler import WindowSettingsHandler


def create_handlers(webui, catalog, settings, library, context=None):
    """Create the domain handlers for one WebUI Container graph."""
    container = webui._container
    return {
        "meme": MemeHandler(catalog, library, context),
        "import": ImportHandler(
            library, getattr(container, "job_manager", None), catalog, context
        ),
        "sync": SyncHandler(container),
        "update": UpdateHandler(webui),
        "window_settings": WindowSettingsHandler(webui, settings, context),
    }
