"""Pytest configuration — mock Home Assistant for unit tests."""

import sys
from unittest.mock import MagicMock

_HA = MagicMock()
sys.modules.setdefault("homeassistant", _HA)
sys.modules.setdefault("homeassistant.config_entries", MagicMock())
sys.modules.setdefault("homeassistant.const", MagicMock())
sys.modules.setdefault("homeassistant.core", MagicMock())
sys.modules.setdefault("homeassistant.data_entry_flow", MagicMock())
sys.modules.setdefault("homeassistant.exceptions", MagicMock())
sys.modules.setdefault("homeassistant.helpers", MagicMock())
sys.modules.setdefault("homeassistant.helpers.entity_platform", MagicMock())
sys.modules.setdefault("homeassistant.helpers.network", MagicMock())
sys.modules.setdefault("homeassistant.helpers.selector", MagicMock())
sys.modules.setdefault("homeassistant.helpers.update_coordinator", MagicMock())
sys.modules.setdefault("homeassistant.components.light", MagicMock())
