from __future__ import annotations

from shared import cache


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.deleted: list[str] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value

    def delete(self, *keys: str):
        for key in keys:
            self.deleted.append(key)
            self.store.pop(key, None)

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key

    def sadd(self, key: str, value: str):
        self.sets.setdefault(key, set()).add(value)

    def smembers(self, key: str):
        return set(self.sets.get(key, set()))


def test_set_json_and_get_json_round_trip():
    client = FakeRedis()
    payload = {"markets": [1, 2, 3]}
    cache.set_json(client, "k1", payload)
    assert cache.get_json(client, "k1") == payload


def test_invalidate_tag_deletes_registered_keys():
    client = FakeRedis()
    cache.set_json(client, "markets:list|offset=0", {"items": []})
    cache.set_json(client, "markets:list|offset=1", {"items": []})
    cache.add_tag(client, "markets:list", "markets:list|offset=0")
    cache.add_tag(client, "markets:list", "markets:list|offset=1")
    removed = cache.invalidate_tag(client, "markets:list")
    assert removed == 2
    assert "markets:list|offset=0" not in client.store
    assert "markets:list|offset=1" not in client.store


def test_get_schema_tag_returns_known_revision():
    client = FakeRedis()
    client.set("schema:key", "rev-123")
    assert cache.get_schema_tag(client, "schema:key") == "schema:rev-123"


def test_get_schema_tag_returns_unknown_when_missing():
    client = FakeRedis()
    assert cache.get_schema_tag(client, "missing") == "schema:unknown"
