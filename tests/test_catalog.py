from __future__ import annotations

import pytest

from bar_benchmarks.orchestrator.catalog import Catalog, key_from_uri

CATALOG = """
[engine.recoil-abc1234]
dest = "gs://bucket/engine/recoil-abc1234.tar.gz"
commit = "abc1234"

[bar_content.bar-test-1-abc1234]
dest = "gs://bucket/bar-content/bar-test-1-abc1234.tar.gz"
version = "Beyond All Reason test-1-abc1234"

[map."with-source"]
dest = "gs://bucket/maps/with-source.sd7"
source = "https://example.com/with-source.sd7"

[map."no-source"]
dest = "gs://bucket/maps/no-source.sd7"
"""


def test_load_and_resolve(tmp_path):
    path = tmp_path / "artifacts.toml"
    path.write_text(CATALOG)
    cat = Catalog.load(path)

    eng = cat.engine("recoil-abc1234")
    assert eng.dest_uri.endswith("/engine/recoil-abc1234.tar.gz")
    assert eng.commit == "abc1234"

    bar = cat.bar_content("bar-test-1-abc1234")
    assert bar.version == "Beyond All Reason test-1-abc1234"

    m1 = cat.map("with-source")
    assert m1.source_url == "https://example.com/with-source.sd7"

    m2 = cat.map("no-source")
    assert m2.source_url is None


def test_missing_entry_raises(tmp_path):
    path = tmp_path / "artifacts.toml"
    path.write_text(CATALOG)
    cat = Catalog.load(path)
    with pytest.raises(KeyError):
        cat.engine("does-not-exist")


def test_key_from_uri():
    assert key_from_uri("gs://b/path/to/thing.tar.gz") == ("b", "path/to/thing.tar.gz")
    with pytest.raises(ValueError):
        key_from_uri("not-a-uri")
    with pytest.raises(ValueError):
        key_from_uri("gs://just-bucket")
