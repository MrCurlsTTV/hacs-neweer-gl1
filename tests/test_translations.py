"""Every user-facing validation error must have a message in the UI strings."""

import json
from pathlib import Path

import pytest

from custom_components.neewer_wifi import config_flow

COMPONENT = Path(__file__).parent.parent / "custom_components" / "neewer_wifi"
ERROR_KEYS = sorted(
    {cls.error_key for cls in config_flow.ValidationError.__subclasses__()}
)


@pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
@pytest.mark.parametrize("error_key", ERROR_KEYS)
def test_validation_error_has_message(path, error_key) -> None:
    errors = json.loads((COMPONENT / path).read_text(encoding="utf-8"))["config"]["error"]
    assert errors.get(error_key), f"{error_key} missing from {path}"
