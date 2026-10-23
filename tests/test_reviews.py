def review(client, api, token, contractor_id, project_id, rating=5, comment="Excellent work"):
    return client.post(
        "/reviews",
        json={
            "contractor_id": contractor_id,
            "project_id": project_id,
            "rating": rating,
            "comment": comment,
        },
        headers=api.auth(token),
    )


def hired(api, client):
    _, customer = api.customer()
    contractor_id, contractor = api.contractor(credits=2)
    project = api.published(customer)
    client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    return customer, contractor_id, contractor, project


def test_review_requires_unlocked_project(api, client):
    _, customer = api.customer()
    contractor_id, _ = api.contractor()
    project = api.published(customer)
    r = review(client, api, customer, contractor_id, project["id"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "review.not_allowed"


def test_customer_cannot_review_via_someone_elses_project(api, client):
    _, contractor_id, _, project = hired(api, client)
    _, other_customer = api.customer()
    r = review(client, api, other_customer, contractor_id, project["id"])
    assert r.status_code == 403


def test_review_shows_on_public_profile(api, client):
    customer, contractor_id, contractor, project = hired(api, client)
    assert review(client, api, customer, contractor_id, project["id"], rating=4).status_code == 201

    # The same contractor unlocks a second customer's project.
    _, customer2 = api.customer()
    project2 = api.published(customer2)
    client.post(f"/projects/{project2['id']}/unlock", headers=api.auth(contractor))
    review(client, api, customer2, contractor_id, project2["id"], rating=5)

    profile = client.get(f"/contractors/{contractor_id}").json()
    assert profile["review_count"] == 2
    assert profile["average_rating"] == 4.5


def test_one_review_per_project(api, client):
    customer, contractor_id, _, project = hired(api, client)
    review(client, api, customer, contractor_id, project["id"])
    r = review(client, api, customer, contractor_id, project["id"])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "review.exists"


def test_rating_bounds(api, client):
    customer, contractor_id, _, project = hired(api, client)
    assert review(client, api, customer, contractor_id, project["id"], rating=0).status_code == 422
    assert review(client, api, customer, contractor_id, project["id"], rating=6).status_code == 422


def test_hidden_reviews_leave_public_profile(api, client):
    customer, contractor_id, _, project = hired(api, client)
    review_id = review(client, api, customer, contractor_id, project["id"], rating=1).json()["id"]
    admin = api.auth(api.admin())

    r = client.patch(f"/admin/reviews/{review_id}", json={"status": "hidden"}, headers=admin)
    assert r.status_code == 200
    profile = client.get(f"/contractors/{contractor_id}").json()
    assert profile["review_count"] == 0
    assert profile["average_rating"] is None

    assert client.patch(f"/admin/reviews/{review_id}", json={"status": "bogus"}, headers=admin).status_code == 422
    assert client.delete(f"/admin/reviews/{review_id}", headers=admin).status_code == 204
    assert client.get("/admin/reviews", headers=admin).json() == []
