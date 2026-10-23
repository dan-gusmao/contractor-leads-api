def checkout(api, client, token, package_id="starter"):
    r = client.post("/credits/checkout", json={"package_id": package_id}, headers=api.auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def send_webhook(client, app, reference, status="paid", signature=None):
    body, good_signature = app.state.payment_provider.sign_event(reference, status)
    return client.post(
        "/payments/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Payment-Signature": signature if signature is not None else good_signature,
        },
    )


def test_packages_are_listed(client):
    packages = client.get("/credits/packages").json()
    assert {p["id"] for p in packages} == {"starter", "pro", "business"}
    assert all(p["currency"] == "EUR" for p in packages)


def test_checkout_creates_pending_payment(api, client):
    _, contractor = api.contractor()
    result = checkout(api, client, contractor)
    assert result["payment"]["status"] == "pending"
    assert result["payment"]["credits"] == 10
    assert result["payment"]["amount_cents"] == 4900
    assert result["checkout_url"].endswith(result["payment"]["provider_reference"])
    assert api.balance(contractor) == 0


def test_unknown_package(api, client):
    _, contractor = api.contractor()
    r = client.post("/credits/checkout", json={"package_id": "mega"}, headers=api.auth(contractor))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "payment.unknown_package"


def test_paid_webhook_adds_credits(api, client, app):
    _, contractor = api.contractor()
    payment = checkout(api, client, contractor, "pro")["payment"]
    r = send_webhook(client, app, payment["provider_reference"])
    assert r.status_code == 200
    assert r.json() == {"status": "paid", "duplicate": False}
    assert api.balance(contractor) == 30

    payments = client.get("/me/payments", headers=api.auth(contractor)).json()
    assert payments[0]["status"] == "paid"
    assert payments[0]["completed_at"] is not None
    kinds = [t["kind"] for t in client.get("/me/credits", headers=api.auth(contractor)).json()["transactions"]]
    assert kinds == ["purchase"]


def test_duplicate_webhook_does_not_double_credit(api, client, app):
    _, contractor = api.contractor()
    reference = checkout(api, client, contractor)["payment"]["provider_reference"]
    send_webhook(client, app, reference)
    r = send_webhook(client, app, reference)
    assert r.json() == {"status": "paid", "duplicate": True}
    # A late "failed" notification must not undo a completed payment either.
    r = send_webhook(client, app, reference, status="failed")
    assert r.json()["status"] == "paid"
    assert api.balance(contractor) == 10


def test_failed_payment_adds_nothing(api, client, app):
    _, contractor = api.contractor()
    reference = checkout(api, client, contractor)["payment"]["provider_reference"]
    r = send_webhook(client, app, reference, status="failed")
    assert r.json() == {"status": "failed", "duplicate": False}
    assert api.balance(contractor) == 0


def test_webhook_signature_is_verified(api, client, app):
    _, contractor = api.contractor()
    reference = checkout(api, client, contractor)["payment"]["provider_reference"]
    r = send_webhook(client, app, reference, signature="forged")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "payment.invalid_signature"
    r = client.post("/payments/webhook", json={"reference": reference, "status": "paid"})
    assert r.status_code == 400
    assert api.balance(contractor) == 0


def test_webhook_for_unknown_reference(client, app):
    r = send_webhook(client, app, "fake_doesnotexist")
    assert r.status_code == 404


def test_purchased_credits_can_unlock(api, client, app):
    _, customer = api.customer()
    project = api.published(customer)
    _, contractor = api.contractor()
    send_webhook(client, app, checkout(api, client, contractor)["payment"]["provider_reference"])
    r = client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    assert r.json()["charged"] is True
    assert r.json()["credit_balance"] == 9
