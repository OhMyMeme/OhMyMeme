"""Desktop bridge UpdateHandler implementation."""


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
