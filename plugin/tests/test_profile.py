# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

from dedala import profile
from dedala.link import Link


def test_the_profile_is_a_store_made_with_the_agent_s_name(tmp_path):
    link = Link(tmp_path, "http://relay", "token", "Jacques")
    assert link.stores.held["profile"] == {"name": "Jacques"}
    link.stores.put("profile", {"name": "Jo"})
    assert Link(tmp_path, "http://relay", "token", "Jacques").stores.held["profile"] == {"name": "Jo"}


def test_a_face_is_made_of_the_parts_the_app_draws(tmp_path):
    picture = tmp_path / "me.png"
    picture.write_bytes(b"png")
    assert profile.problem({"name": "Jo", "look": {"skin": "edb98a", "top": "none"}, "picture": str(picture)}) is None
    assert "choose one of ffdbb4" in profile.problem({"name": "Jo", "look": {"skin": "green"}})
    assert "no part hat" in profile.problem({"name": "Jo", "look": {"hat": "fedora"}})
    assert "image file on this machine" in profile.problem({"name": "Jo", "picture": "https://example.com/me.png"})
    assert profile.problem({"look": {}}) == "profile needs a name"


def test_the_agent_hears_what_he_changed_of_its_name_and_face():
    assert profile.told({"name": "Jacques"}, {"name": "Jo"}).startswith("[app: he named you Jo in the app, instead of Jacques")
    assert "he made your face over" in profile.told({"name": "Jo"}, {"name": "Jo", "look": {"skin": "edb98a"}})
    assert "he gave you a picture for a face, /p.png" in profile.told({"name": "Jo"}, {"name": "Jo", "picture": "/p.png"})
    assert "the drawn look now" in profile.told({"name": "Jo", "picture": "/p.png"}, {"name": "Jo"})
    assert profile.told({"name": "Jo"}, {"name": "Jo"}) is None


def test_the_picture_goes_to_the_phone_like_a_record_s_file(tmp_path):
    link = Link(tmp_path, "http://relay", "token", "Jacques")
    picture = tmp_path / "me.png"
    picture.write_bytes(b"png")
    link.stores.put("profile", {"name": "Jacques", "picture": str(picture)})
    assert link.stores.attachments("profile") == [("picture", picture)]
    assert link.fetch("profile", "picture") is None
