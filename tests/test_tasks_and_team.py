from datetime import date, timedelta


def test_task_filters(client, pipeline, upload, alice):
    upload(alice)
    tasks = {t["title"]: t for t in client.get("/api/tasks/", headers=alice).json()}
    devis = tasks["Envoyer le devis"]
    assert [t["id"] for t in client.get("/api/tasks/?overdue=true", headers=alice).json()] == [devis["id"]]
    assert len(client.get("/api/tasks/?assignee=ali ben salah", headers=alice).json()) == 1
    assert len(client.get("/api/tasks/?status=todo", headers=alice).json()) == 2
    assert client.get("/api/tasks/?status=done", headers=alice).json() == []
    assert client.get("/api/tasks/?status=nimporte", headers=alice).status_code == 422


def test_patch_task_status_priority_assignee_and_due_date(client, pipeline, upload, alice):
    upload(alice)
    task = client.get("/api/tasks/", headers=alice).json()[0]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    body = {"status": "in_progress", "priority": "low", "due_date": tomorrow, "assignee": " Sara "}
    p = client.patch(f"/api/tasks/{task['id']}", json=body, headers=alice).json()
    assert (p["status"], p["priority"], p["due_date"], p["assignee"]) == ("in_progress", "low", tomorrow, "Sara")

    p = client.patch(f"/api/tasks/{task['id']}", json={"assignee": None, "due_date": None}, headers=alice).json()
    assert p["assignee"] is None and p["due_date"] is None and p["status"] == "in_progress"   # le reste est intact


def test_done_tasks_are_not_overdue(client, pipeline, upload, alice):
    upload(alice)
    overdue = client.get("/api/tasks/?overdue=true", headers=alice).json()[0]
    client.patch(f"/api/tasks/{overdue['id']}", json={"status": "done"}, headers=alice)
    assert client.get("/api/tasks/?overdue=true", headers=alice).json() == []


def test_team_crud(client, alice):
    team = client.post("/api/team/", json={"name": "Dev"}, headers=alice)
    assert team.status_code == 201
    tid = team.json()["id"]
    member = {"full_name": "Ali Ben Salah", "email": "ali@x.com", "role": "Dev"}
    m = client.post(f"/api/team/{tid}/members", json=member, headers=alice)
    assert m.status_code == 201
    assert client.get("/api/team/", headers=alice).json()[0]["member_count"] == 1
    assert len(client.get(f"/api/team/{tid}", headers=alice).json()["members"]) == 1
    assert client.delete(f"/api/team/{tid}/members/{m.json()['id']}", headers=alice).status_code == 204
    assert client.get("/api/team/members", headers=alice).json() == []
    assert client.post(f"/api/team/{tid}/members", json={"full_name": ""}, headers=alice).status_code == 422


def test_workload_matches_names_without_accents_and_ignores_ambiguous_first_names(client, pipeline, upload, alice):
    pipeline.analysis["tasks"] = [
        {"title": "T1", "assignee": "ali ben salah", "confidence": 1, "priority": "low"},
        {"title": "T2", "assignee": "Hélène", "confidence": 1, "priority": "low"},
        {"title": "T3", "assignee": "Karim", "confidence": 1, "priority": "low"},
    ]
    tid = client.post("/api/team/", json={"name": "Dev"}, headers=alice).json()["id"]
    for name in ("Ali Ben Salah", "Hélène Martin", "Karim Un", "Karim Deux"):
        client.post(f"/api/team/{tid}/members", json={"full_name": name}, headers=alice)
    upload(alice)
    counts = {m["full_name"]: m["task_count"] for m in client.get("/api/team/members", headers=alice).json()}
    assert counts["Ali Ben Salah"] == 1                       # casse ignorée
    assert counts["Hélène Martin"] == 1                       # prénom seul, non ambigu, accents ignorés
    assert counts["Karim Un"] == 0 and counts["Karim Deux"] == 0   # "Karim" est ambigu : personne n'est crédité
