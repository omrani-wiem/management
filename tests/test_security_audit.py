def test_authenticated_api_requests_are_audited_without_request_content(client, alice, bob):
    task_list = client.get("/api/tasks/?assignee=person@example.com", headers=alice)
    assert task_list.status_code == 200
    assert task_list.headers.get("X-Request-ID")

    alice_events = client.get("/api/audit/", headers=alice)
    assert alice_events.status_code == 200
    event = next(item for item in alice_events.json() if item["endpoint"] == "/api/tasks/")
    assert event["method"] == "GET"
    assert event["status_code"] == 200
    assert event["request_id"] == task_list.headers["X-Request-ID"]
    assert event["resource_id"] is None
    assert "person@example.com" not in str(event)

    bob_events = client.get("/api/audit/", headers=bob)
    assert bob_events.status_code == 200
    assert all(item["id"] != event["id"] for item in bob_events.json())


def test_audit_records_failed_requests_and_resource_id(client, alice):
    response = client.patch(
        "/api/tasks/11111111-1111-4111-8111-111111111111",
        json={"status": "done"},
        headers=alice,
    )
    assert response.status_code == 404

    events = client.get("/api/audit/", headers=alice).json()
    event = next(item for item in events if item["endpoint"] == "/api/tasks/{task_id}")
    assert event["method"] == "PATCH"
    assert event["resource_id"] == "11111111-1111-4111-8111-111111111111"
    assert event["status_code"] == 404
