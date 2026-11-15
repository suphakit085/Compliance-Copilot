"""The evaluation page must never show the tuned set's numbers without the blind ones."""

from fastapi.testclient import TestClient


def test_eval_sets_lists_tuned_and_blind_results_side_by_side(corpus):
    from compliance_copilot.api.main import app
    from compliance_copilot.security import seed_users

    seed_users()
    with TestClient(app) as client:
        tok = client.post("/auth/login", json={"username": "somchai", "password": "demo-employee"}).json()["access_token"]
        rows = {r["key"]: r for r in client.get("/eval/sets", headers={"Authorization": f"Bearer {tok}"}).json()}
    assert rows["main"]["tuned"] and not rows["main"]["blind"]
    assert rows["holdout_blind"]["blind"] and rows["extended_blind"]["blind"]
    # the extended blind run's answers live in a separate as-run file and must still be shown
    assert rows["extended_blind"]["behaviour"] == 0.945 and rows["extended_blind"]["key_facts"] == 0.914
    assert all(r["leakage"] == 0 for r in rows.values())
