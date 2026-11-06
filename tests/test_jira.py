from datetime import date
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.task import TaskPriority
from app.services import jira


def test_create_and_refresh_jira_ticket(client, pipeline, upload, alice, bob, monkeypatch):
    upload(alice)
    task = client.get("/api/tasks/", headers=alice).json()[0]
    calls = []

    def create_issue(found_task, meeting_title):
        calls.append((found_task.title, meeting_title))
        return "MEET-42", "https://example.atlassian.net/browse/MEET-42"

    monkeypatch.setattr("app.routers.tasks.jira_service.create_issue", create_issue)
    created = client.post(f"/api/tasks/{task['id']}/jira", headers=alice)
    assert created.status_code == 200
    assert created.json()["jira_issue_key"] == "MEET-42"
    assert created.json()["jira_issue_url"].endswith("/MEET-42")
    assert calls == [("Envoyer le devis", "Sprint")]

    duplicate = client.post(f"/api/tasks/{task['id']}/jira", headers=alice)
    assert duplicate.status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/jira", headers=bob).status_code == 404

    monkeypatch.setattr("app.routers.tasks.jira_service.get_issue_status", lambda key: "In Progress")
    refreshed = client.post(f"/api/tasks/{task['id']}/jira/refresh", headers=alice)
    assert refreshed.status_code == 200
    assert refreshed.json()["jira_status"] == "In Progress"


def test_jira_rest_payload_and_authentication(monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", "https://example.atlassian.net/")
    monkeypatch.setattr(settings, "jira_email", "owner@example.com")
    monkeypatch.setattr(settings, "jira_api_token", "secret-token")
    monkeypatch.setattr(settings, "jira_project_key", "MEET")
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"key": "MEET-42"}

    class Client:
        def __init__(self, timeout, auth):
            requests.append({"timeout": timeout, "auth": auth})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def post(self, url, json):
            requests.append({"url": url, "payload": json})
            return Response()

    monkeypatch.setattr(jira.httpx, "Client", Client)
    task = SimpleNamespace(
        title="Contacter alice@example.com",
        description="Utiliser l'IBAN GB82 WEST 1234 5698 7654 32 et la carte 4111 1111 1111 1111.",
        priority=TaskPriority.high,
        due_date=date(2026, 12, 1),
    )
    assert jira.create_issue(task, "Sprint") == (
        "MEET-42",
        "https://example.atlassian.net/browse/MEET-42",
    )
    assert requests[0] == {"timeout": 15.0, "auth": ("owner@example.com", "secret-token")}
    assert requests[1]["url"] == "https://example.atlassian.net/rest/api/3/issue"
    fields = requests[1]["payload"]["fields"]
    assert fields["project"] == {"key": "MEET"}
    assert fields["summary"] == "Contacter [EMAIL]"
    jira_description = str(fields["description"])
    assert "GB82 WEST 1234 5698 7654 32" not in jira_description
    assert "4111 1111 1111 1111" not in jira_description
    assert fields["priority"] == {"name": "High"}
    assert fields["duedate"] == "2026-12-01"


def test_jira_configuration_is_required(monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", None)
    monkeypatch.setattr(settings, "jira_email", None)
    monkeypatch.setattr(settings, "jira_api_token", None)
    monkeypatch.setattr(settings, "jira_project_key", None)

    with pytest.raises(jira.JiraError) as error:
        jira._configuration()
    assert error.value.status_code == 503


def test_refresh_reads_the_jira_workflow_status(monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", "https://example.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "owner@example.com")
    monkeypatch.setattr(settings, "jira_api_token", "secret-token")
    monkeypatch.setattr(settings, "jira_project_key", "MEET")
    requests = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"fields": {"status": {"name": "In Progress"}}}

    class Client:
        def __init__(self, timeout, auth):
            requests.append({"timeout": timeout, "auth": auth})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, url, params):
            requests.append({"url": url, "params": params})
            return Response()

    monkeypatch.setattr(jira.httpx, "Client", Client)
    assert jira.get_issue_status("MEET-42") == "In Progress"
    assert requests[1] == {
        "url": "https://example.atlassian.net/rest/api/3/issue/MEET-42",
        "params": {"fields": "status"},
    }


def test_jira_base_url_must_use_https_without_embedded_credentials(monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", "http://example.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "owner@example.com")
    monkeypatch.setattr(settings, "jira_api_token", "secret-token")
    monkeypatch.setattr(settings, "jira_project_key", "MEET")

    with pytest.raises(jira.JiraError) as error:
        jira._configuration()
    assert error.value.status_code == 503
