from dataclasses import replace

from app.models import ContactUnlock, CreditTransaction


def test_unlock_requires_credits(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor(credits=0)
    project = api.published(customer)

    r = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "credits.insufficient"
    assert "Required 1, available 0" in r.json()["error"]["message"]


def test_unlock_reveals_contact_and_charges_once(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor(credits=3)
    project = api.published(customer)

    first = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor)).json()
    assert first["charged"] is True
    assert first["credit_balance"] == 2
    assert first["contact"] == {
        "name": "Maija Meikäläinen",
        "email": "maija@example.com",
        "phone": "+358401234567",
    }

    second = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor)).json()
    assert second["charged"] is False
    assert second["credit_balance"] == 2
    assert api.balance(contractor) == 2

    detail = client.get(f"/projects/{project['id']}", headers=api.auth(contractor)).json()
    assert detail["contact_locked"] is False
    assert detail["contact"]["email"] == "maija@example.com"


def test_many_contractors_can_unlock_same_project(api, client, app):
    _, customer = api.customer()
    project = api.published(customer)
    contractors = [api.contractor(credits=1) for _ in range(4)]
    for _, token in contractors:
        r = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(token))
        assert r.json()["charged"] is True

    with app.state.session_factory() as db:
        assert db.query(ContactUnlock).filter_by(project_id=project["id"]).count() == 4


def test_cannot_unlock_unpublished_project(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor(credits=5)
    draft = api.draft(customer)
    r = client.post(f"/projects/{draft['id']}/unlock", headers=api.auth(contractor))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "project.not_public"
    assert api.balance(contractor) == 5


def test_unlock_needs_contractor_profile(api, client):
    _, customer = api.customer()
    project = api.published(customer)
    _, bare_contractor = api.register("contractor")
    r = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(bare_contractor))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "profile.missing"


def test_unlocked_contact_survives_project_removal(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor(credits=1)
    project = api.published(customer)
    client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    client.post(
        f"/admin/projects/{project['id']}/remove",
        json={"reason": "Customer hired someone"},
        headers=api.auth(api.admin()),
    )

    unlocks = client.get("/me/unlocks", headers=api.auth(contractor)).json()
    assert len(unlocks) == 1
    assert unlocks[0]["project"]["contact"]["email"] == "maija@example.com"
    # Re-unlocking a removed project the contractor already paid for is free.
    r = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    assert r.status_code == 200
    assert r.json()["charged"] is False


def test_unlock_cost_is_configurable(api, client, app):
    app.state.settings = replace(app.state.settings, unlock_cost=3)
    _, customer = api.customer()
    _, contractor = api.contractor(credits=5)
    project = api.published(customer)
    assert project["unlock_cost"] == 3
    r = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    assert r.json()["credits_spent"] == 3
    assert api.balance(contractor) == 2


def test_ledger_records_every_change(api, client):
    contractor_id, contractor = api.contractor(credits=2)
    _, customer = api.customer()
    project = api.published(customer)
    client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))

    transactions = client.get("/me/credits", headers=api.auth(contractor)).json()["transactions"]
    assert [(t["kind"], t["amount"], t["balance_after"]) for t in transactions] == [
        ("unlock", -1, 1),
        ("admin_grant", 2, 2),
    ]
    assert transactions[0]["project_id"] == project["id"]


def test_admin_adjustment_cannot_go_negative(api, client, app):
    contractor_id, contractor = api.contractor(credits=2)
    r = client.post(
        f"/admin/contractors/{contractor_id}/credits",
        json={"amount": -5, "reason": "correction"},
        headers=api.auth(api.admin()),
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "credits.negative_balance"
    assert api.balance(contractor) == 2

    r = client.post(
        f"/admin/contractors/{contractor_id}/credits",
        json={"amount": -2, "reason": "correction"},
        headers=api.auth(api.admin()),
    )
    assert r.status_code == 201
    assert r.json()["kind"] == "admin_adjustment"
    assert api.balance(contractor) == 0

    with app.state.session_factory() as db:
        assert db.query(CreditTransaction).filter_by(contractor_id=contractor_id).count() == 2


def test_admin_credit_validation(api, client):
    contractor_id, _ = api.contractor()
    customer_id, _ = api.customer()
    admin = api.auth(api.admin())
    r = client.post(
        f"/admin/contractors/{contractor_id}/credits", json={"amount": 0, "reason": "zero"}, headers=admin
    )
    assert r.status_code == 422
    r = client.post(
        f"/admin/contractors/{customer_id}/credits", json={"amount": 5, "reason": "oops"}, headers=admin
    )
    assert r.status_code == 404
