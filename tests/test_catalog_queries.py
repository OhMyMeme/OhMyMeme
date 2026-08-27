from types import SimpleNamespace

from ohmymeme.app.catalog import Catalog
from ohmymeme.core.database import MemeDB


class _Library:
    def __init__(self, db):
        self._db = db

    def is_favorite(self, meme_id):
        return self._db.is_favorite(meme_id)


def _catalog(tmp_path):
    db = MemeDB(tmp_path / "memes.db")
    catalog = Catalog(
        SimpleNamespace(get=lambda key, default=None: default),
        db,
        lambda: None,
        library=_Library(db),
    )
    return db, catalog


def test_catalog_search_and_count_share_combined_query_results(tmp_path):
    db, catalog = _catalog(tmp_path)
    try:
        cat = db.add_meme("cat.png", original_name="friendly", tags=["animal", "cute"])
        dog = db.add_meme("dog.png", original_name="friendly", tags=["animal"])
        hidden = db.add_meme(
            "carrier.gif", tags=["animal", "cute"], stego_of_hash="cat"
        )
        group = db.create_collection("pets")
        child = db.create_collection("small", group)
        db.add_to_collection(cat, child)
        db.add_to_collection(dog, group)
        db.toggle_favorite(cat)

        rows = catalog.search_memes(
            keyword="friendly", tags=["animal", "cute"], collection_id=group
        )

        assert [row["id"] for row in rows] == [cat]
        assert catalog.count_memes(
            keyword="friendly", tags=["animal", "cute"], collection_id=group
        ) == len(rows)
        assert hidden not in [row["id"] for row in rows]
        assert catalog.search_memes(collection_id=-2)[0]["id"] == cat
        assert catalog.search_memes(collection_id=-4) == []
    finally:
        db.close()


def test_catalog_query_edges_do_not_expand_virtual_or_invalid_collections(tmp_path):
    db, catalog = _catalog(tmp_path)
    try:
        first = db.add_meme("first.png", tags=["one"])
        second = db.add_meme("second.png", tags=["two"])
        db.record_use(first)
        db.record_use(second)
        db.reorder_memes([first, second])

        assert catalog.search_memes(tags=[]) == catalog.search_memes(tags=None)
        assert catalog.search_memes(tags=["missing"]) == []
        assert catalog.search_memes(collection_id=999999) == []
        assert catalog.search_memes(collection_id=-3, offset=99) == []
        assert catalog.count_memes(collection_id=-3) == 2
        assert catalog.count_memes(collection_id=-4) == 2
        assert [row["id"] for row in catalog.search_memes(limit=1, offset=1)] == [
            second
        ]
    finally:
        db.close()


def test_get_collections_recent_count_matches_recent_query(tmp_path):
    db, catalog = _catalog(tmp_path)
    try:
        first = db.add_meme("first.png")
        second = db.add_meme("second.png")
        db.record_use(first)
        db.record_use(second)

        recent = catalog.search_memes(collection_id=-3)
        collections = catalog.get_collections()

        assert next(item["count"] for item in collections if item["id"] == -3) == len(
            recent
        )
        assert catalog.count_memes(collection_id=-3) == len(recent)
    finally:
        db.close()
