import pytest

from app.validators import is_valid_business_id


@pytest.mark.parametrize(
    "value, valid",
    [
        ("0112038-9", True),
        ("1572860-0", True),  # remainder 0 -> check digit 0
        ("0112038-8", False),  # wrong check digit
        ("112038-9", False),  # too short
        ("01120389", False),  # missing dash
        ("1234567-1", True),
        ("0000006-0", False),  # remainder 1 -> no valid check digit exists
    ],
)
def test_business_id_validation(value, valid):
    assert is_valid_business_id(value) is valid


def test_customer_profile_create_and_update(api, client):
    _, token = api.register("customer")
    assert client.get("/me/customer-profile", headers=api.auth(token)).status_code == 404

    r = client.put(
        "/me/customer-profile", json={"full_name": "Anna", "city": "Espoo"}, headers=api.auth(token)
    )
    assert r.status_code == 200
    r = client.put(
        "/me/customer-profile", json={"full_name": "Anna K", "city": "Vantaa"}, headers=api.auth(token)
    )
    assert r.json() == {"full_name": "Anna K", "phone": None, "city": "Vantaa"}


def test_contractor_profile_with_business_id(api, client):
    _, token = api.register("contractor")
    r = client.put(
        "/me/contractor-profile",
        json={
            "company_name": "Putki Oy",
            "business_id": "0112038-9",
            "services": ["plumbing", "plumbing", "maintenance"],
            "service_area": "Uusimaa",
        },
        headers=api.auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business_id"] == "0112038-9"
    assert body["services"] == ["plumbing", "maintenance"]
    assert body["credit_balance"] == 0


def test_business_id_is_optional_but_validated(api, client):
    _, token = api.register("contractor")
    r = client.put(
        "/me/contractor-profile",
        json={"company_name": "No ID Oy"},
        headers=api.auth(token),
    )
    assert r.status_code == 200
    assert r.json()["business_id"] is None

    r = client.put(
        "/me/contractor-profile",
        json={"company_name": "Bad ID Oy", "business_id": "0112038-8"},
        headers=api.auth(token),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation.invalid_business_id"


def test_unknown_service_category_rejected(api, client):
    _, token = api.register("contractor")
    r = client.put(
        "/me/contractor-profile",
        json={"company_name": "X Oy", "services": ["space-travel"]},
        headers=api.auth(token),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation.invalid_category"


def test_public_contractor_profile_hides_private_data(api, client):
    contractor_id, _ = api.contractor(credits=5)
    r = client.get(f"/contractors/{contractor_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["company_name"].endswith("Oy")
    assert body["review_count"] == 0
    assert body["average_rating"] is None
    assert "credit_balance" not in body
    assert "phone" not in body


def test_public_contractor_list_filters(api, client):
    api.contractor()
    _, token = api.register("contractor")
    client.put(
        "/me/contractor-profile",
        json={"company_name": "Sähkö Oy", "services": ["electrical"], "service_area": "Tampere"},
        headers=api.auth(token),
    )
    assert [c["company_name"] for c in client.get("/contractors?service=electrical").json()] == [
        "Sähkö Oy"
    ]
    assert len(client.get("/contractors?area=tampere").json()) == 1
    assert len(client.get("/contractors").json()) == 2


def test_customers_are_not_public_contractors(api, client):
    customer_id, _ = api.customer()
    assert client.get(f"/contractors/{customer_id}").status_code == 404
