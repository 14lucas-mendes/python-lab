from pathlib import Path

from python_lab.storage.paths import AppPaths, resolve_paths


def test_data_dir_is_outside_catalog(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sentinel = catalog / "mission.json"
    sentinel.write_text("original", encoding="utf-8")
    explicit_dir = tmp_path / "state"

    paths = resolve_paths(catalog, explicit_dir)

    assert paths == AppPaths(catalog_dir=catalog, data_dir=explicit_dir)
    assert sentinel.read_text(encoding="utf-8") == "original"
    assert not explicit_dir.exists()


def test_default_data_dir_uses_platformdirs(tmp_path, monkeypatch):
    expected = tmp_path / "user-data" / "python-lab"
    calls = []

    def fake_user_data_path(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr("python_lab.storage.paths.platformdirs.user_data_path", fake_user_data_path)
    paths = resolve_paths(tmp_path / "catalog", None)

    assert paths.data_dir == expected
    assert calls
    assert paths.catalog_dir == tmp_path / "catalog"
    assert not expected.exists()
