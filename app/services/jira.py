from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models.task import Task


@dataclass
class JiraError(Exception):
    message: str
    status_code: int = 502


def _configuration() -> tuple[str, str, str, str]:
    base_url = settings.jira_base_url
    email = settings.jira_email
    api_token = settings.jira_api_token
    project_key = settings.jira_project_key
    if not base_url or not email or not api_token or not project_key:
        raise JiraError("L'intégration Jira n'est pas configurée", status_code=503)

    base_url = base_url.rstrip("/")
    parsed_url = urlparse(base_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise JiraError("JIRA_BASE_URL doit être une URL HTTPS valide", status_code=503)
    return base_url, email, api_token, project_key


def create_issue(task: Task, meeting_title: str) -> tuple[str, str]:
    base_url, email, api_token, project_key = _configuration()
    description = task.description or "Tâche extraite d'une réunion."
    content = [
        {"type": "paragraph", "content": [{"type": "text", "text": description}]},
        {"type": "paragraph", "content": [{"type": "text", "text": f"Réunion : {meeting_title}"}]},
    ]
    fields = {
        "project": {"key": project_key},
        "summary": task.title,
        "description": {"type": "doc", "version": 1, "content": content},
        "issuetype": {"name": "Task"},
        "priority": {"name": {"high": "High", "medium": "Medium", "low": "Low"}[task.priority.value]},
    }
    if task.due_date:
        fields["duedate"] = task.due_date.isoformat()

    try:
        with httpx.Client(timeout=15.0, auth=(email, api_token)) as client:
            response = client.post(f"{base_url}/rest/api/3/issue", json={"fields": fields})
            response.raise_for_status()
            issue = response.json()
    except httpx.HTTPStatusError as exc:
        raise JiraError("Jira a refusé la création du ticket (vérifie les identifiants et le projet)") from exc
    except httpx.HTTPError as exc:
        raise JiraError("Jira est momentanément inaccessible") from exc
    except ValueError as exc:
        raise JiraError("Jira a renvoyé une réponse invalide") from exc

    issue_key = issue.get("key") if isinstance(issue, dict) else None
    if not isinstance(issue_key, str) or not issue_key:
        raise JiraError("La réponse Jira ne contient pas de clé de ticket")
    return issue_key, f"{base_url}/browse/{issue_key}"


def get_issue_status(issue_key: str) -> str:
    base_url, email, api_token, _ = _configuration()
    try:
        with httpx.Client(timeout=15.0, auth=(email, api_token)) as client:
            response = client.get(
                f"{base_url}/rest/api/3/issue/{issue_key}",
                params={"fields": "status"},
            )
            response.raise_for_status()
            issue = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise JiraError("Ticket introuvable dans Jira", status_code=404) from exc
        raise JiraError("Jira a refusé la lecture du ticket") from exc
    except httpx.HTTPError as exc:
        raise JiraError("Jira est momentanément inaccessible") from exc
    except ValueError as exc:
        raise JiraError("Jira a renvoyé une réponse invalide") from exc

    try:
        status_name = issue["fields"]["status"]["name"]
    except (KeyError, TypeError) as exc:
        raise JiraError("La réponse Jira ne contient pas de statut") from exc
    if not isinstance(status_name, str) or not status_name.strip():
        raise JiraError("La réponse Jira ne contient pas de statut")
    return status_name
