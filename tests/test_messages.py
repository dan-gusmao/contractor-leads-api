def setup_unlocked(api, client):
    _, customer = api.customer()
    contractor_id, contractor = api.contractor(credits=1)
    project = api.published(customer)
    client.post(f"/projects/{project['id']}/unlock", headers=api.auth(contractor))
    return customer, contractor_id, contractor, project


def test_contractor_must_unlock_before_messaging(api, client):
    _, customer = api.customer()
    _, contractor = api.contractor(credits=1)
    project = api.published(customer)
    r = client.post(
        f"/projects/{project['id']}/conversations",
        json={"body": "Hello!"},
        headers=api.auth(contractor),
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "message.not_allowed"


def test_project_conversation_flow(api, client):
    customer, contractor_id, contractor, project = setup_unlocked(api, client)

    r = client.post(
        f"/projects/{project['id']}/conversations",
        json={"body": "Hi, I can start next week."},
        headers=api.auth(contractor),
    )
    assert r.status_code == 201, r.text
    conversation = r.json()
    assert conversation["project_title"] == "Bathroom renovation"
    assert conversation["contractor_id"] == contractor_id

    inbox = client.get("/me/conversations", headers=api.auth(customer)).json()
    assert [c["id"] for c in inbox] == [conversation["id"]]

    r = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"body": "Great, what's your quote?"},
        headers=api.auth(customer),
    )
    assert r.status_code == 201

    history = client.get(f"/conversations/{conversation['id']}", headers=api.auth(contractor)).json()
    assert [m["body"] for m in history["messages"]] == [
        "Hi, I can start next week.",
        "Great, what's your quote?",
    ]


def test_starting_twice_reuses_conversation(api, client):
    _, _, contractor, project = setup_unlocked(api, client)
    url = f"/projects/{project['id']}/conversations"
    first = client.post(url, json={"body": "One"}, headers=api.auth(contractor)).json()
    second = client.post(url, json={"body": "Two"}, headers=api.auth(contractor)).json()
    assert first["id"] == second["id"]
    assert len(second["messages"]) == 2


def test_customer_can_start_with_contractor_who_unlocked(api, client):
    customer, contractor_id, _, project = setup_unlocked(api, client)
    other_id, _ = api.contractor()
    url = f"/projects/{project['id']}/conversations"

    r = client.post(url, json={"body": "Hi", "contractor_id": other_id}, headers=api.auth(customer))
    assert r.status_code == 403
    r = client.post(url, json={"body": "Hi", "contractor_id": contractor_id}, headers=api.auth(customer))
    assert r.status_code == 201


def test_outsiders_cannot_read_or_post(api, client):
    _, _, contractor, project = setup_unlocked(api, client)
    conversation = client.post(
        f"/projects/{project['id']}/conversations", json={"body": "Hi"}, headers=api.auth(contractor)
    ).json()
    _, stranger = api.contractor()
    url = f"/conversations/{conversation['id']}"
    assert client.get(url, headers=api.auth(stranger)).status_code == 404
    r = client.post(f"{url}/messages", json={"body": "Hi"}, headers=api.auth(stranger))
    assert r.status_code == 404


def test_blank_messages_rejected(api, client):
    _, _, contractor, project = setup_unlocked(api, client)
    r = client.post(
        f"/projects/{project['id']}/conversations", json={"body": "   "}, headers=api.auth(contractor)
    )
    assert r.status_code == 422
