from guardian_account_isolation import assert_kill_switch_update_is_account_scoped

def test_rejects_unscoped_guardian_update():
    try:
        assert_kill_switch_update_is_account_scoped("UPDATE guardian_state SET daily_kill_switch = TRUE", ())
    except RuntimeError as exc:
        assert "missing_account_id_scope" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

def test_accepts_scoped_guardian_update():
    assert_kill_switch_update_is_account_scoped("UPDATE guardian_state SET daily_kill_switch = TRUE WHERE account_id = %s", (1,))
