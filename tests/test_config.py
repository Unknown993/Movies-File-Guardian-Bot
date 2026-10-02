"""Unit tests for configuration and permission checks."""

import pytest
import config
from config import DeliveryMode, is_developer, is_admin, _parse_int_set


def test_delivery_mode_from_str():
    assert DeliveryMode.from_str("view_only") == DeliveryMode.VIEW_ONLY
    assert DeliveryMode.from_str("VIEW_ONLY") == DeliveryMode.VIEW_ONLY
    assert DeliveryMode.from_str("view") == DeliveryMode.VIEW_ONLY
    assert DeliveryMode.from_str("protected") == DeliveryMode.VIEW_ONLY

    assert DeliveryMode.from_str("downloadable") == DeliveryMode.DOWNLOADABLE
    assert DeliveryMode.from_str("DOWNLOADABLE") == DeliveryMode.DOWNLOADABLE
    assert DeliveryMode.from_str("download") == DeliveryMode.DOWNLOADABLE
    assert DeliveryMode.from_str("auto_delete") == DeliveryMode.DOWNLOADABLE

    with pytest.raises(ValueError):
        DeliveryMode.from_str("invalid_mode")


def test_parse_int_set():
    assert _parse_int_set("") == set()
    assert _parse_int_set(None) == set()
    assert _parse_int_set("123, 456, 789") == {123, 456, 789}
    assert _parse_int_set("123, invalid, 456") == {123, 456}


def test_permission_checks(monkeypatch):
    monkeypatch.setattr(config, "DEVELOPER_ID", 1001)
    monkeypatch.setattr(config, "ADMIN_IDS", {1001, 2002})

    assert is_developer(1001) is True
    assert is_developer(2002) is False
    assert is_developer(9999) is False

    assert is_admin(1001) is True
    assert is_admin(2002) is True
    assert is_admin(9999) is False
