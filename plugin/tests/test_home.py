# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

from dedala.hermes import internals


def test_the_former_folder_moves_once_and_its_path_still_leads_there(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "hermes_app" / "stores").mkdir(parents=True)
    (tmp_path / "hermes_app" / "stores" / "notes.json").write_text("{}")
    home = internals.home()
    assert home == tmp_path / "dedala"
    assert (home / "stores" / "notes.json").read_text() == "{}"
    assert (tmp_path / "hermes_app").is_symlink()
    assert (tmp_path / "hermes_app" / "stores" / "notes.json").exists()
    assert internals.home() == home


def test_a_new_home_is_dedala(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert internals.home() == tmp_path / "dedala"
    assert not (tmp_path / "hermes_app").exists()
