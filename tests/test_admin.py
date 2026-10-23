from .test_payments import checkout, send_webhook


def test_admin_routes_require_admin(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor()
    for token in (customer, contractor):
        assert client.get("/admin/reports", headers=api.auth(token)).status_code == 403
    assert client.get("/admin/reports").status_code == 401


def test_list_users_by_role(api, client):
    api.customer()
    api.contractor()
    api.contractor()
    admin = api.auth(api.admin())
    assert len(client.get("/admin/users?role=contractor", headers=admin).json()) == 2
    assert len(client.get("/admin/users?role=customer", headers=admin).json()) == 1
    assert len(client.get("/admin/users", headers=admin).json()) == 4  # includes the admin


def test_admin_cannot_suspend_self(api, client):
    admin = api.auth(api.admin())
    me = client.get("/auth/me", headers=admin).json()
    r = client.patch(f"/admin/users/{me['id']}/status", json={"status": "suspended"}, headers=admin)
    assert r.status_code == 403


def test_suspended_contractor_hidden_from_public(api, client):
    contractor_id, _ = api.contractor()
    client.patch(
        f"/admin/users/{contractor_id}/status",
        json={"status": "suspended"},
        headers=api.auth(api.admin()),
    )
    assert client.get(f"/contractors/{contractor_id}").status_code == 404
    assert client.get("/contractors").json() == []


def test_unlock_history_and_transactions(api, client):
    _, customer = api.customer()
    contractor_id, contractor = api.contractor(credits=1)
    project = api.published(customer)
    client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    admin = api.auth(api.admin())

    unlocks = client.get(f"/admin/unlocks?project_id={project['id']}", headers=admin).json()
    assert [(u["contractor_id"], u["credits_spent"]) for u in unlocks] == [(contractor_id, 1)]
    unlock_tx = client.get("/admin/transactions?kind=unlock", headers=admin).json()
    assert len(unlock_tx) == 1


def test_marketplace_report(api, client, app):
    admin = api.auth(api.admin())
    _, customer = api.customer()
    contractor_id, contractor = api.contractor(credits=3)  # manual credits
    _, contractor2 = api.contractor()

    published = api.published(customer)
    pending = api.draft(customer, title="Second project")
    client.post(f"/projects/{pending['id']}/submit", headers=api.auth(customer))
    api.draft(customer, title="Never submitted")

    reference = checkout(api, client, contractor2, "starter")["payment"]["provider_reference"]
    send_webhook(client, app, reference)

    client.post(f"/projects/{published['id']}/unlock", headers=api.auth(contractor))
    client.post(f"/projects/{published['id']}/unlock", headers=api.auth(contractor2))
    client.post(
        f"/projects/{published['id']}/conversations", json={"body": "Hello"}, headers=api.auth(contractor)
    )
    client.post(
        "/reviews",
        json={"contractor_id": contractor_id, "project_id": published["id"], "rating": 5},
        headers=api.auth(customer),
    )

    report = client.get("/admin/reports", headers=admin).json()
    assert report == {
        "customers": 1,
        "contractors": 2,
        "projects_submitted": 2,
        "projects_approved": 1,
        "projects_published": 1,
        "contact_unlocks": 2,
        "credits_purchased": 10,
        "credits_manually_assigned": 3,
        "credits_used": 2,
        "messages_sent": 1,
        "reviews_submitted": 1,
        "revenue_cents": 4900,
    }
