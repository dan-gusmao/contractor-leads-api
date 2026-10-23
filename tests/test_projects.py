from .conftest import PROJECT

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def test_draft_is_private_until_approved(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    assert project["status"] == "draft"

    assert client.get(f"/projects/{project['id']}").status_code == 404
    assert client.get("/projects").json()["total"] == 0
    # The owner can still see their own draft.
    assert client.get(f"/projects/{project['id']}", headers=api.auth(customer)).status_code == 200


def test_submit_approve_publish_flow(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    r = client.post(f"/projects/{project['id']}/submit", headers=api.auth(customer))
    assert r.json()["status"] == "submitted"

    pending = client.get("/admin/projects?status=submitted", headers=api.auth(api.admin())).json()
    assert [p["id"] for p in pending] == [project["id"]]

    r = client.post(f"/admin/projects/{project['id']}/approve", headers=api.auth(api.admin()))
    assert r.json()["status"] == "published"
    listing = client.get("/projects").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == project["id"]


def test_rejection_reason_and_resubmission(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    client.post(f"/projects/{project['id']}/submit", headers=api.auth(customer))
    r = client.post(
        f"/admin/projects/{project['id']}/reject",
        json={"reason": "Please add a budget range."},
        headers=api.auth(api.admin()),
    )
    assert r.json()["status"] == "rejected"

    mine = client.get("/me/projects", headers=api.auth(customer)).json()
    assert mine[0]["rejection_reason"] == "Please add a budget range."

    r = client.post(f"/projects/{project['id']}/submit", headers=api.auth(customer))
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"
    assert r.json()["rejection_reason"] is None


def test_invalid_transitions(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    # Drafts cannot be approved before submission.
    r = client.post(f"/admin/projects/{project['id']}/approve", headers=api.auth(api.admin()))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "project.invalid_transition"

    client.post(f"/projects/{project['id']}/submit", headers=api.auth(customer))
    r = client.post(f"/projects/{project['id']}/submit", headers=api.auth(customer))
    assert r.status_code == 409


def test_editing_published_project_requires_new_approval(api, client):
    _, customer = api.customer()
    project = api.published(customer)
    r = client.patch(
        f"/projects/{project['id']}", json={"title": "Bigger bathroom"}, headers=api.auth(customer)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"
    assert client.get("/projects").json()["total"] == 0


def test_removed_project_cannot_be_edited(api, client):
    _, customer = api.customer()
    project = api.published(customer)
    client.post(
        f"/admin/projects/{project['id']}/remove",
        json={"reason": "Spam"},
        headers=api.auth(api.admin()),
    )
    r = client.patch(f"/projects/{project['id']}", json={"title": "Again"}, headers=api.auth(customer))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "project.not_editable"


def test_only_owner_can_edit(api, client):
    _, owner = api.customer()
    _, other = api.customer()
    project = api.draft(owner)
    r = client.patch(f"/projects/{project['id']}", json={"title": "Mine now"}, headers=api.auth(other))
    assert r.status_code == 404


def test_project_validation(api, client):
    _, customer = api.customer()
    r = client.post(
        "/projects", json={**PROJECT, "category": "unknown"}, headers=api.auth(customer)
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation.invalid_category"

    r = client.post(
        "/projects", json={**PROJECT, "budget_min": 10, "budget_max": 5}, headers=api.auth(customer)
    )
    assert r.json()["error"]["code"] == "validation.invalid_budget"

    project = api.draft(customer)
    r = client.patch(
        f"/projects/{project['id']}", json={"budget_min": 99999}, headers=api.auth(customer)
    )
    assert r.json()["error"]["code"] == "validation.invalid_budget"


def test_contractors_cannot_create_projects(api, client):
    _, contractor = api.contractor()
    assert client.post("/projects", json=PROJECT, headers=api.auth(contractor)).status_code == 403


def test_contact_is_hidden_from_public_and_contractors(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor()
    project = api.published(customer)

    for headers in ({}, api.auth(contractor)):
        body = client.get(f"/projects/{project['id']}", headers=headers).json()
        assert body["contact_locked"] is True
        assert body["contact"] is None
        assert "maija@example.com" not in str(body)

    owner_view = client.get(f"/projects/{project['id']}", headers=api.auth(customer)).json()
    assert owner_view["contact"]["email"] == "maija@example.com"


def test_search_and_filters(api, client):
    _, customer = api.customer()
    api.published(customer)
    api.published(
        customer,
        title="Roof repair",
        description="Replace damaged roof tiles on a detached house.",
        category="roofing",
        location="Tampere",
        budget_min=1000,
        budget_max=2000,
    )
    api.published(
        customer,
        title="Fence painting",
        description="Paint a 40 metre wooden garden fence.",
        category="painting",
        budget_min=None,
        budget_max=None,
    )

    def ids(query: str) -> list[str]:
        return sorted(p["title"] for p in client.get(f"/projects{query}").json()["items"])

    assert ids("?q=roof") == ["Roof repair"]
    assert ids("?q=TILING") == ["Bathroom renovation"]
    assert ids("?category=roofing") == ["Roof repair"]
    assert ids("?location=tamp") == ["Roof repair"]
    # Budget filters match overlapping ranges; projects without a budget always match.
    assert ids("?budget_min=3000") == ["Bathroom renovation", "Fence painting"]
    assert ids("?budget_max=1500") == ["Fence painting", "Roof repair"]
    assert ids("?budget_min=2500&budget_max=4000") == ["Fence painting"]


def test_pagination(api, client):
    _, customer = api.customer()
    for i in range(3):
        api.published(customer, title=f"Project number {i}")
    page = client.get("/projects?limit=2&offset=0").json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert len(client.get("/projects?limit=2&offset=2").json()["items"]) == 1


def test_view_count_ignores_owner(api, client, app):
    _, customer = api.customer()
    project = api.published(customer)
    client.get(f"/projects/{project['id']}")
    client.get(f"/projects/{project['id']}")
    client.get(f"/projects/{project['id']}", headers=api.auth(customer))
    from app.models import Project

    with app.state.session_factory() as db:
        assert db.get(Project, project["id"]).view_count == 2


def test_image_upload_and_download(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    r = client.post(
        f"/projects/{project['id']}/images",
        files={"file": ("photo.png", PNG, "image/png")},
        headers=api.auth(customer),
    )
    assert r.status_code == 201, r.text
    image = r.json()
    assert image["content_type"] == "image/png"

    # Draft images are private; published images are public.
    assert client.get(image["url"]).status_code == 404
    assert client.get(image["url"], headers=api.auth(customer)).content == PNG


def test_image_type_is_detected_from_content(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    r = client.post(
        f"/projects/{project['id']}/images",
        files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")},
        headers=api.auth(customer),
    )
    assert r.status_code == 415
    r = client.post(
        f"/projects/{project['id']}/images",
        files={"file": ("photo.txt", JPEG, "text/plain")},
        headers=api.auth(customer),
    )
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/jpeg"


def test_image_limits(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    url = f"/projects/{project['id']}/images"
    big = PNG + b"\x00" * 2048
    r = client.post(url, files={"file": ("big.png", big, "image/png")}, headers=api.auth(customer))
    assert r.status_code == 413

    for _ in range(2):
        client.post(url, files={"file": ("a.png", PNG, "image/png")}, headers=api.auth(customer))
    r = client.post(url, files={"file": ("c.png", PNG, "image/png")}, headers=api.auth(customer))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "image.too_many"


def test_delete_image(api, client):
    _, customer = api.customer()
    project = api.draft(customer)
    image = client.post(
        f"/projects/{project['id']}/images",
        files={"file": ("a.png", PNG, "image/png")},
        headers=api.auth(customer),
    ).json()
    assert client.delete(image["url"], headers=api.auth(customer)).status_code == 204
    assert client.get(image["url"], headers=api.auth(customer)).status_code == 404


def test_finnish_language_support(api, client):
    _, customer = api.customer()
    project = api.published(customer)

    body = client.get(f"/projects/{project['id']}", headers={"Accept-Language": "fi-FI,fi;q=0.9"}).json()
    assert body["category_label"] == "Remontti"
    assert client.get(f"/projects/{project['id']}?lang=en").json()["category_label"] == "Renovation"

    labels = {c["id"]: c["label"] for c in client.get("/categories?lang=fi").json()}
    assert labels["plumbing"] == "Putkityöt"

    r = client.get("/projects/9999", headers={"Accept-Language": "fi"})
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "project.not_found", "message": "Projektia ei löytynyt."}
