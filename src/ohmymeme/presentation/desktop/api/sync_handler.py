"""Desktop bridge SyncHandler implementation."""


class SyncHandler:
    """Owns the Container-created sync service factory and progress seam."""

    def __init__(self, container):
        self.container = container

    def service(self):
        return self.container.create_sync_service()

    def progress(self):
        from ohmymeme.services.sync import service

        return service.get_sync_progress()

    def push(self, delete_remote=None):
        try:
            sync_service = self.service()
        except Exception as error:
            return {"ok": False, "error": str(error), "failed_files": []}
        try:
            result = sync_service.push(delete_remote=delete_remote)
            result["ok"] = True
            return result
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
                "failed_files": self.progress().get("failed_items", []),
            }

    def pull(self, remove_local=None, refresh=False):
        try:
            sync_service = self.service()
        except Exception as error:
            return {"ok": False, "error": str(error), "failed_files": []}
        try:
            result = sync_service.pull(remove_local=remove_local)
            result["ok"] = True
            if refresh:
                try:
                    import webview

                    if webview.windows:
                        webview.windows[0].evaluate_js(
                            "refreshMemes();refreshTags();refreshCollections();"
                        )
                except Exception:
                    pass
            return result
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
                "failed_files": self.progress().get("failed_items", []),
            }

    def auto_sync(self):
        try:
            return self.service().auto_sync()
        except Exception as error:
            return {"fetched": False, "synced": False, "error": str(error)}

    def test_connection(self):
        try:
            return self.service().test_connection()
        except Exception as error:
            return str(error)

    def delete_all_remote(self):
        try:
            return self.service().delete_all_remote()
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def cleanup_remote_orphans(self, delete=False):
        try:
            return self.service().cleanup_remote_orphans(delete=delete)
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def status(self):
        try:
            return self.service().get_status()
        except AttributeError:
            return {"ok": False, "error": "同步状态服务不可用"}
        except Exception as error:
            return {"ok": False, "error": str(error)}
