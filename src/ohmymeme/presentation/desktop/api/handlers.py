"""Desktop bridge domain handlers sharing the Container-owned graph."""


class MemeHandler:
    """Owns references used by meme and collection bridge operations."""

    def __init__(self, catalog, library):
        self.catalog = catalog
        self.library = library

    def search_memes(
        self, keyword="", tags=None, collection_id=None, offset=0, limit=200
    ):
        return self.catalog.search_memes(keyword, tags, collection_id, offset, limit)

    def count_memes(self, keyword="", tags=None, collection_id=None):
        return self.catalog.count_memes(keyword, tags, collection_id)

    def get_tags(self):
        return self.catalog.get_tags()

    def get_meme_path(self, meme_id):
        return self.catalog.get_meme_path(meme_id)

    def get_meme_paths(self, meme_ids):
        return self.catalog.get_meme_paths(meme_ids)

    def toggle_favorite(self, meme_id):
        return self.library.toggle_favorite(meme_id)

    def is_favorite(self, meme_id):
        return self.library.is_favorite(meme_id)


class ImportHandler:
    """Owns the application import boundary for bridge import operations."""

    def __init__(self, library, job_manager):
        self.library = library
        self.job_manager = job_manager

    def import_paths(self, paths, names=None):
        return self.library.import_paths(paths, names)


class SyncHandler:
    """Owns the Container-created sync service factory and progress seam."""

    def __init__(self, container):
        self.container = container

    def service(self):
        return self.container.create_sync_service()

    def progress(self):
        from ohmymeme.services.sync import service

        return service.get_sync_progress()


class UpdateHandler:
    """Owns update operations while leaving WebUI quit wiring in the facade."""

    def __init__(self, webui):
        self.webui = webui

    def check_update(self, debug=False, force=False):
        from ohmymeme import __version__ as current_version
        from ohmymeme.services import updates

        info = updates.check_latest_cached(force=bool(debug) or bool(force))
        info["current"] = current_version
        if debug or self.webui._update_debug:
            info["has_update"] = True
        return info

    def start_download(self, url):
        from ohmymeme.services import updates

        return updates.start_download(url)

    def download_progress(self):
        from ohmymeme.services import updates

        return updates.get_download_progress()

    def run_downloaded_installer(self):
        from ohmymeme.services import updates

        return updates.run_downloaded_installer()

    def download_update(self, url):
        from ohmymeme.services import updates

        path = updates.download_release(url)
        if not path:
            return {"ok": False, "error": "download failed"}
        ok = updates.run_installer(path)
        return {"ok": ok, "error": "" if ok else "run installer failed"}


class WindowSettingsHandler:
    """Owns shared settings dependencies without constructing a second graph."""

    def __init__(self, webui, settings):
        self.webui = webui
        self.settings = settings
        self.config = webui._cfg


def create_handlers(webui, catalog, settings, library):
    """Create the domain handlers for one WebUI Container graph."""
    container = webui._container
    return {
        "meme": MemeHandler(catalog, library),
        "import": ImportHandler(library, getattr(container, "job_manager", None)),
        "sync": SyncHandler(container),
        "update": UpdateHandler(webui),
        "window_settings": WindowSettingsHandler(webui, settings),
    }
