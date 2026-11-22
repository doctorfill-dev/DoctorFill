"""
Cache OCR (ocr_cache.py) : le texte d'un dossier ne survit pas à la rétention.

Données fictives uniquement (« Patient Test »).
"""

import json
from pathlib import Path

from ocr_cache import OcrCache, purge_legacy_disk_cache

HASH_A = "a" * 64
HASH_B = "b" * 64
PAYLOAD = dict(markdown="Patient Test, né le 01.01.1970", mode="text_layer")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_entry_is_served_until_it_expires():
    clock = FakeClock()
    cache = OcrCache(max_entries=10, ttl_seconds=3600, clock=clock)
    cache.put(HASH_A, PAYLOAD)
    clock.now += 3599
    assert cache.get(HASH_A) == PAYLOAD
    clock.now += 1
    assert cache.get(HASH_A) is None
    assert len(cache) == 0


def test_reading_an_entry_does_not_extend_its_life():
    clock = FakeClock()
    cache = OcrCache(max_entries=10, ttl_seconds=60, clock=clock)
    cache.put(HASH_A, PAYLOAD)
    for _ in range(5):
        clock.now += 20
        cache.get(HASH_A)
    assert cache.get(HASH_A) is None


def test_expired_entries_are_purged_from_memory_on_any_write():
    clock = FakeClock()
    cache = OcrCache(max_entries=10, ttl_seconds=60, clock=clock)
    cache.put(HASH_A, PAYLOAD)
    clock.now += 61
    cache.put(HASH_B, PAYLOAD)
    assert len(cache) == 1


def test_size_limit_drops_the_oldest_entry():
    cache = OcrCache(max_entries=1, ttl_seconds=3600, clock=FakeClock())
    cache.put(HASH_A, PAYLOAD)
    cache.put(HASH_B, PAYLOAD)
    assert cache.get(HASH_A) is None
    assert cache.get(HASH_B) == PAYLOAD


def test_zero_ttl_disables_the_cache():
    cache = OcrCache(max_entries=10, ttl_seconds=0, clock=FakeClock())
    cache.put(HASH_A, PAYLOAD)
    assert cache.get(HASH_A) is None
    assert len(cache) == 0


def test_returned_payload_is_a_copy():
    cache = OcrCache(max_entries=10, ttl_seconds=3600, clock=FakeClock())
    cache.put(HASH_A, PAYLOAD)
    cache.get(HASH_A)["markdown"] = "modifié"
    assert cache.get(HASH_A) == PAYLOAD


def test_cache_never_writes_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = OcrCache(max_entries=10, ttl_seconds=3600, clock=FakeClock())
    cache.put(HASH_A, PAYLOAD)
    assert list(tmp_path.iterdir()) == []


def _write_entry(path: Path) -> None:
    path.write_text(json.dumps(PAYLOAD), encoding="utf-8")


def test_legacy_disk_cache_entries_are_removed(tmp_path: Path):
    legacy = tmp_path / "doctorfill_ocr"
    legacy.mkdir()
    _write_entry(legacy / f"{HASH_A}.json")
    _write_entry(legacy / f"{HASH_B}.json")
    assert purge_legacy_disk_cache(legacy) == 2
    assert not legacy.exists()


def test_legacy_purge_leaves_other_files_alone(tmp_path: Path):
    legacy = tmp_path / "doctorfill_ocr"
    legacy.mkdir()
    _write_entry(legacy / f"{HASH_A}.json")
    keep = [legacy / "model.safetensors", legacy / "notes.json", legacy / f"{HASH_B}.json.bak"]
    for path in keep:
        path.write_text("x", encoding="utf-8")
    assert purge_legacy_disk_cache(legacy) == 1
    assert all(path.exists() for path in keep)


def test_legacy_purge_without_directory_is_a_no_op(tmp_path: Path):
    assert purge_legacy_disk_cache(tmp_path / "absent") == 0
