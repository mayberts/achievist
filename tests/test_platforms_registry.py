"""
Sanity checks on the platform registry and each platform's connect schema.

These exist because the frontend's ConnectModal renders CONNECT_FIELDS
generically — a malformed schema on a new platform would silently break the
Accounts UI rather than raising an error, so we check the contract here.
"""

import pytest

from app.platforms import PLATFORMS
from app.platforms.base import Platform

ALLOWED_FIELD_TYPES = {"text", "password", "select"}


@pytest.mark.parametrize("key,cls", list(PLATFORMS.items()))
def test_platform_key_matches_registry_key(key, cls):
    assert cls.KEY == key, f"{cls.__name__}.KEY ({cls.KEY!r}) must match its registry key ({key!r})"


@pytest.mark.parametrize("key,cls", list(PLATFORMS.items()))
def test_platform_declares_a_label(key, cls):
    assert cls.LABEL, f"{cls.__name__} must set a non-empty LABEL"


@pytest.mark.parametrize("key,cls", list(PLATFORMS.items()))
def test_platform_is_a_platform_subclass_with_sync(key, cls):
    assert issubclass(cls, Platform)
    assert callable(getattr(cls, "sync", None))


@pytest.mark.parametrize("key,cls", list(PLATFORMS.items()))
def test_connect_fields_are_well_formed(key, cls):
    # oauth platforms (device-code flow, e.g. Xbox) may have no form fields
    if cls.AUTH_TYPE == "oauth" and not cls.CONNECT_FIELDS:
        return
    for field in cls.CONNECT_FIELDS:
        assert "name" in field and field["name"], f"{key}: field missing 'name'"
        assert "label" in field and field["label"], f"{key}: field {field.get('name')} missing 'label'"
        assert field.get("type") in ALLOWED_FIELD_TYPES, (
            f"{key}: field {field['name']} has unsupported type {field.get('type')!r}"
        )
        if field["type"] == "select":
            assert field.get("options"), f"{key}: select field {field['name']} needs 'options'"


@pytest.mark.parametrize("key,cls", list(PLATFORMS.items()))
def test_connect_schema_serializes(key, cls):
    schema = cls.connect_schema()
    assert schema["key"] == key
    assert schema["label"] == cls.LABEL
    assert schema["auth_type"] in ("form", "oauth")
    assert schema["fields"] == cls.CONNECT_FIELDS
