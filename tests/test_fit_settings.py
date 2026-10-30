"""Owned fit defaults, exact numeric settings and immutable CAS history."""

import pytest
from sqlalchemy import inspect


def fresh(client_factory, register):
    c = client_factory()
    auth = register(c)
    h = {"X-CSRF-Token": auth["csrf_token"]}
    p = c.post("/api/projects", json={"name": "Fit"}, headers=h).json()
    return c, h, p, f"/api/projects/{p['id']}/fit-settings"


def defaults():
    return dict(
        mode="fixed",
        max_audio_speed={"numerator": 6, "denominator": 5},
        max_picture_factor={"numerator": 2, "denominator": 1},
        max_borrow_ms=0,
        max_output_duration_ms=57_600_000,
    )


def test_default_read_creates_nothing_and_first_explicit_defaults_save(client_factory, register):
    c, h, p, url = fresh(client_factory, register)
    response = c.get(url)
    assert response.status_code == 200, response.text
    assert response.json() == dict(
        revision=0, policy="shared_fit_v1", settings=defaults(), history=[], total=0
    )
    with c.app.state.engine.connect() as db:
        from sqlalchemy import text

        assert db.scalar(text("select count(*) from fit_settings_states")) == 0
    saved = c.put(url, headers=h, json=dict(revision=0, settings=defaults()))
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1 and len(saved.json()["history"]) == 1
    assert saved.json()["history"][0]["actor_id"]
    assert c.put(url, headers=h, json=dict(revision=0, settings=defaults())).status_code == 409
    assert c.put(url, json=dict(revision=1, settings=defaults())).status_code == 403
    assert "fit_settings_states" in inspect(c.app.state.engine).get_table_names()


@pytest.mark.parametrize("value", [True, 1.1, "2", 0, -1, 4_000_001])
def test_rate_rejects_coercion_and_bounds(client_factory, register, value):
    c, h, _, url = fresh(client_factory, register)
    settings = defaults()
    settings["max_audio_speed"]["numerator"] = value
    assert c.put(url, headers=h, json=dict(revision=0, settings=settings)).status_code == 422


def test_canonical_noop_history_and_project_ownership(client_factory, register):
    c, h, p, url = fresh(client_factory, register)
    settings = defaults()
    settings["max_audio_speed"] = {"numerator": 12, "denominator": 10}
    first = c.put(url, headers=h, json=dict(revision=0, settings=settings))
    assert first.status_code == 200, first.text
    assert first.json()["settings"] == defaults()
    same = c.put(url, headers=h, json=dict(revision=1, settings=defaults())).json()
    assert same["revision"] == 1 and same["total"] == 1
    settings["max_borrow_ms"] = 500
    saved = c.put(url, headers=h, json=dict(revision=1, settings=settings)).json()
    assert (
        saved["revision"] == 2
        and saved["history"][0]["parent_version_id"] == same["history"][0]["id"]
    )
    assert c.get(url + "?limit=1&offset=1").json()["history"][0]["revision"] == 1
    assert c.get(url + "?limit=101").status_code == 422
    other = client_factory(database_url=c.app.state.settings.database_url.get_secret_value())
    register(other, "fit-other@example.com")
    assert other.get(url).status_code == 404
