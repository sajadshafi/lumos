"""Opt-in live tracker smoke test.

Nothing runs in normal CI. Maintainers can point this at a disposable ticket to
verify the active MCP bridge or REST credentials without committing secrets.
"""

from __future__ import annotations

import json
import os
import unittest

from ai_loom.adapters import create_adapter


@unittest.skipUnless(os.environ.get("LUMOS_INTEGRATION_PROVIDER"), "live tracker test not configured")
class LiveTrackerTests(unittest.TestCase):
    def test_fetch_and_optional_comment(self):
        provider = os.environ["LUMOS_INTEGRATION_PROVIDER"]
        work_id = os.environ["LUMOS_INTEGRATION_WORK_ID"]
        transport = os.environ.get("LUMOS_INTEGRATION_TRANSPORT", "mcp")
        options = json.loads(os.environ.get("LUMOS_INTEGRATION_OPTIONS", "{}"))
        adapter = create_adapter(provider, transport=transport, options=options)

        unit = adapter.fetch(work_id)
        self.assertTrue(unit.id)
        self.assertTrue(unit.title)

        if os.environ.get("LUMOS_INTEGRATION_WRITE") == "1":
            adapter.comment(unit.id, "Lumos live adapter smoke test completed successfully.")


if __name__ == "__main__":
    unittest.main()
