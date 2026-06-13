from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.schemas.lawyer_profile_schema import LawyerProfileCreate, LawyerProfileUpdate


class _EmptyQuery:
    def filter(self, *_args: object, **_kwargs: object) -> "_EmptyQuery":
        return self

    def one_or_none(self) -> None:
        return None


class _EmptyDb:
    def get(self, *_args: object, **_kwargs: object) -> None:
        return None

    def query(self, *_args: object, **_kwargs: object) -> _EmptyQuery:
        return _EmptyQuery()


class _DbWithProfile(_EmptyDb):
    def get(self, *_args: object, **_kwargs: object) -> object:
        return object()


def test_lawyer_profile_routes_are_registered() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/lawyer-profiles" in route_paths
    assert "/lawyer-profiles/by-user/{user_id}" in route_paths
    assert "/lawyer-profiles/{profile_id}" in route_paths


def test_lawyer_profile_by_user_route_is_not_shadowed() -> None:
    app.dependency_overrides[get_db] = lambda: _EmptyDb()
    client = TestClient(app)

    try:
        response = client.get("/lawyer-profiles/by-user/missing-user")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Lawyer profile not found"


def test_lawyer_profile_create_requires_system_prompt() -> None:
    response = LawyerProfileCreate.model_validate(
        {"user_id": "user-1", "system_prompt": "Act as a Ukrainian contract lawyer."}
    )

    assert response.user_id == "user-1"
    assert response.system_prompt == "Act as a Ukrainian contract lawyer."


def test_lawyer_profile_update_allows_partial_payload() -> None:
    response = LawyerProfileUpdate.model_validate({"specialization": "Contract disputes"})

    assert response.specialization == "Contract disputes"
    assert response.system_prompt is None


def test_lawyer_profile_update_rejects_null_system_prompt() -> None:
    app.dependency_overrides[get_db] = lambda: _DbWithProfile()
    client = TestClient(app)

    try:
        response = client.patch("/lawyer-profiles/profile-1", json={"system_prompt": None})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "system_prompt cannot be null"
