"""What each role may do, and that one organisation cannot reach into another."""

from tests.conftest import PASSWORD

NEW = {"email": "new-hire@example.test", "password": PASSWORD, "name": "New", "role": "viewer"}


async def test_only_admins_manage_users(team):
    for client in (team.viewer, team.agent):
        assert (await client.get("/api/users")).status_code == 403
        assert (await client.post("/api/users", json=NEW)).status_code == 403
        assert (await client.get("/api/audit")).status_code == 403
    listed = (await team.admin.get("/api/users")).json()["users"]
    assert sorted(u["role"] for u in listed) == ["admin", "agent", "supervisor", "viewer"]


async def test_admin_sees_only_their_own_organisation(team, other_team):
    emails = {u["email"] for u in (await team.admin.get("/api/users")).json()["users"]}
    assert emails == set(team.emails.values())
    assert not emails & set(other_team.emails.values())


async def test_admin_cannot_modify_a_user_of_another_organisation(team, other_team):
    r = await team.admin.patch(f"/api/users/{other_team.user_ids['viewer']}", json={"role": "admin"})
    assert r.status_code == 404
    assert (await other_team.viewer.get("/api/auth/me")).json()["user"]["role"] == "viewer"


async def test_role_change_takes_effect_on_the_next_request(team):
    assert (await team.viewer.get("/api/users")).status_code == 403
    r = await team.admin.patch(f"/api/users/{team.user_ids['viewer']}", json={"role": "admin"})
    assert r.status_code == 200
    assert (await team.viewer.get("/api/users")).status_code == 200


async def test_deactivated_user_is_signed_out_and_cannot_sign_in(client, team):
    r = await team.admin.patch(f"/api/users/{team.user_ids['agent']}", json={"is_active": False})
    assert r.status_code == 200
    assert (await team.agent.get("/api/auth/me")).status_code == 401
    r = await client.post("/api/auth/login", json={"email": team.emails["agent"], "password": PASSWORD})
    assert r.status_code == 401


async def test_last_admin_cannot_be_demoted_or_deactivated(team):
    me = team.user_ids["admin"]
    assert (await team.admin.patch(f"/api/users/{me}", json={"role": "viewer"})).status_code == 409
    assert (await team.admin.patch(f"/api/users/{me}", json={"is_active": False})).status_code == 409


async def test_user_changes_are_written_to_the_audit_log(team):
    await team.admin.patch(f"/api/users/{team.user_ids['viewer']}", json={"role": "agent"})
    entries = (await team.admin.get("/api/audit", params={"action": "user."})).json()["entries"]
    actions = [e["action"] for e in entries]
    assert actions.count("user.created") == 3 and actions[0] == "user.updated"
    assert entries[0]["detail"] == {"role": "agent"}
    assert entries[0]["user"] == team.emails["admin"]


async def test_invalid_role_is_rejected(team):
    assert (await team.admin.post("/api/users", json=NEW | {"role": "owner"})).status_code == 422


async def test_simultaneous_creations_with_one_address_give_one_created_and_one_conflict(team):
    import asyncio

    body = {
        "email": team.emails["viewer"].replace("viewer", "dupe"),
        "password": "Correct-Horse-9",
        "name": "Dup",
        "role": "agent",
    }
    results = await asyncio.gather(team.admin.post("/api/users", json=body), team.admin.post("/api/users", json=body))
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
