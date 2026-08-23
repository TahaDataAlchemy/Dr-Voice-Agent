import uuid


def test_create_returns_201_with_envelope_and_normalized_fields(client, patient_payload):
    resp = client.post("/patients", json=patient_payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert uuid.UUID(data["patient_id"])
    assert data["phone_number"] == "4155550139"
    assert data["state"] == "CA"
    assert data["date_of_birth"] == "1995-07-21"
    assert data["insurance_member_id"] == "UH123456"
    assert data["preferred_language"] == "English"
    assert data["emergency_contact_phone"] == "4155550140"
    assert data["status"] == "active"
    assert data["created_at"].endswith("Z") or "+00:00" in data["created_at"]


def test_create_validation_errors_are_field_specific(client, patient_payload):
    patient_payload.update({"date_of_birth": "03/14/2087", "phone_number": "555", "zip_code": "ABC", "state": "ZZ"})
    resp = client.post("/patients", json=patient_payload)
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    fields = {d["field"]: d["message"] for d in error["details"]}
    assert "future" in fields["date_of_birth"]
    assert "10-digit" in fields["phone_number"]
    assert "zip" in fields["zip_code"]
    assert "state" in fields["state"]


def test_missing_required_and_unknown_fields(client):
    resp = client.post("/patients", json={"first_name": "Only"})
    assert resp.status_code == 422
    fields = {d["field"] for d in resp.json()["error"]["details"]}
    assert {"last_name", "phone_number", "city"} <= fields
    # DOB / sex / address / state / zip are optional now, so they must NOT be flagged as missing
    assert {"date_of_birth", "sex", "address_line_1", "state", "zip_code"}.isdisjoint(fields)
    resp = client.post("/patients", json={"nope": 1})
    assert resp.status_code == 422


def test_minimal_registration_only_name_phone_city(client):
    resp = client.post("/patients", json={"first_name": "Ada", "last_name": "Lovelace", "phone_number": "415 555 0142", "city": "Austin"})
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["phone_number"] == "4155550142" and data["city"] == "Austin"
    assert data["date_of_birth"] is None and data["sex"] is None and data["state"] is None and data["zip_code"] is None


def test_malformed_json_is_400(client):
    resp = client.post("/patients", content="{not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_list_filters(client, patient_payload):
    client.post("/patients", json=patient_payload)
    other = {**patient_payload, "last_name": "Reyes", "phone_number": "7185550102", "date_of_birth": "11/02/1974"}
    client.post("/patients", json=other)

    assert len(client.get("/patients").json()["data"]) == 2
    assert [p["last_name"] for p in client.get("/patients", params={"last_name": "khan"}).json()["data"]] == ["Khan"]
    assert len(client.get("/patients", params={"date_of_birth": "11/02/1974"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"date_of_birth": "1974-11-02"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"phone_number": "(718) 555-0102"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"q": "rey"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"q": "415"}).json()["data"]) == 1
    bad = client.get("/patients", params={"date_of_birth": "not-a-date"})
    assert bad.status_code == 422


def test_get_update_delete_cycle(client, patient_payload):
    pid = client.post("/patients", json=patient_payload).json()["data"]["patient_id"]

    assert client.get(f"/patients/{pid}").status_code == 200
    assert client.get(f"/patients/{uuid.uuid4()}").status_code == 404
    assert client.get("/patients/not-a-uuid").status_code == 422

    upd = client.put(f"/patients/{pid}", json={"city": "Oakland", "zip_code": "946121234"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["data"]["city"] == "Oakland"
    assert upd.json()["data"]["zip_code"] == "94612-1234"
    assert upd.json()["data"]["first_name"] == "Aisha"  # untouched
    assert client.put(f"/patients/{pid}", json={"phone_number": "12"}).status_code == 422

    deleted = client.delete(f"/patients/{pid}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted_at"]
    assert client.get(f"/patients/{pid}").status_code == 404
    assert client.delete(f"/patients/{pid}").status_code == 404
    assert client.get("/patients").json()["data"] == []
    listing = client.get("/patients", params={"include_deleted": "true"}).json()["data"]
    assert listing[0]["status"] == "deleted"
    assert client.get(f"/patients/{pid}", params={"include_deleted": "true"}).status_code == 200


def test_api_v1_alias(client, patient_payload):
    resp = client.post("/api/v1/patients", json=patient_payload)
    assert resp.status_code == 201
    assert client.get("/api/v1/patients").json()["data"]


def test_seeded_demo_user_exists(client):
    resp = client.post("/api/v1/auth/login", json={"email": "demo@example.com", "password": "demo12345"})
    assert resp.status_code == 200
