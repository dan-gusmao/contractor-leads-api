import itertools

import pytest
from fastapi.testclient import TestClient

from app import security
from app.config import Settings
from app.main import create_app

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-password"
PASSWORD = "correct-horse"

PROJECT = {
    "title": "Bathroom renovation",
    "description": "Full renovation of a 5 m2 bathroom including tiling and plumbing.",
    "category": "renovation",
    "location": "Helsinki",
    "budget_min": 5000,
    "budget_max": 9000,
    "contact_name": "Maija Meikäläinen",
    "contact_email": "maija@example.com",
    "contact_phone": "+358401234567",
}

_counter = itertools.count(1)


class Api:
    """Small helper around the test client for common marketplace flows."""

    def __init__(self, client: TestClient):
        self.client = client

    @staticmethod
    def auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def register(self, role: str, email: str | None = None) -> tuple[int, str]:
        email = email or f"{role}{next(_counter)}@example.com"
        r = self.client.post(
            "/auth/register", json={"email": email, "password": PASSWORD, "role": role}
        )
        assert r.status_code == 201, r.text
        return r.json()["id"], self.login(email)

    def login(self, email: str, password: str = PASSWORD) -> str:
        r = self.client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    def admin(self) -> str:
        return self.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    def customer(self) -> tuple[int, str]:
        user_id, token = self.register("customer")
        r = self.client.put(
            "/me/customer-profile", json={"full_name": "Test Customer"}, headers=self.auth(token)
        )
        assert r.status_code == 200, r.text
        return user_id, token

    def contractor(self, credits: int = 0) -> tuple[int, str]:
        user_id, token = self.register("contractor")
        r = self.client.put(
            "/me/contractor-profile",
            json={"company_name": f"Rakennus {user_id} Oy", "services": ["renovation"]},
            headers=self.auth(token),
        )
        assert r.status_code == 200, r.text
        if credits:
            self.grant(user_id, credits)
        return user_id, token

    def grant(self, contractor_id: int, amount: int) -> None:
        r = self.client.post(
            f"/admin/contractors/{contractor_id}/credits",
            json={"amount": amount, "reason": "beta credits"},
            headers=self.auth(self.admin()),
        )
        assert r.status_code == 201, r.text

    def draft(self, token: str, **overrides) -> dict:
        r = self.client.post("/projects", json={**PROJECT, **overrides}, headers=self.auth(token))
        assert r.status_code == 201, r.text
        return r.json()

    def published(self, token: str, **overrides) -> dict:
        project = self.draft(token, **overrides)
        r = self.client.post(f"/projects/{project['id']}/submit", headers=self.auth(token))
        assert r.status_code == 200, r.text
        r = self.client.post(
            f"/admin/projects/{project['id']}/approve", headers=self.auth(self.admin())
        )
        assert r.status_code == 200, r.text
        return r.json()

    def balance(self, token: str) -> int:
        return self.client.get("/me/credits", headers=self.auth(token)).json()["credit_balance"]


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    # Hashes store their own iteration count, so verification is unaffected.
    monkeypatch.setattr(security, "PBKDF2_ITERATIONS", 1_000)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite://",
        secret_key="test-secret",
        payment_webhook_secret="test-webhook-secret",
        media_dir=str(tmp_path / "media"),
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        max_images_per_project=2,
        max_image_bytes=1024,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def api(client) -> Api:
    return Api(client)
