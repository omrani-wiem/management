"""Un utilisateur ne doit jamais voir ni modifier les données d'un autre."""


def test_user_b_cannot_access_user_a_data(client, pipeline, upload, alice, bob):
    mid = upload(alice, participants="Ali").json()["id"]
    team = client.post("/api/team/", json={"name": "Dev"}, headers=alice).json()
    task_id = client.get("/api/tasks/", headers=alice).json()[0]["id"]

    assert client.get(f"/api/meetings/{mid}", headers=bob).status_code == 404
    assert client.get(f"/api/meetings/{mid}/segments", headers=bob).status_code == 404
    assert client.get(f"/api/tasks/meeting/{mid}", headers=bob).status_code == 404
    assert client.get(f"/api/team/{team['id']}", headers=bob).status_code == 404
    assert client.patch(f"/api/tasks/{task_id}", json={"status": "done"}, headers=bob).status_code == 404
    assert client.post(f"/api/team/{team['id']}/members", json={"full_name": "Intrus"}, headers=bob).status_code == 404

    assert client.get("/api/meetings/", headers=bob).json() == []
    assert client.get("/api/tasks/", headers=bob).json() == []
    assert client.get("/api/team/", headers=bob).json() == []
    assert client.get("/api/team/members", headers=bob).json() == []


def test_known_names_never_leak_between_users(client, pipeline, upload, alice, bob):
    team = client.post("/api/team/", json={"name": "Equipe secrète"}, headers=alice).json()
    client.post(f"/api/team/{team['id']}/members", json={"full_name": "Nom Confidentiel"}, headers=alice)
    upload(bob)
    prompts = " ".join(m["content"] for msgs in pipeline.prompts for m in msgs)
    assert "Nom Confidentiel" not in prompts
