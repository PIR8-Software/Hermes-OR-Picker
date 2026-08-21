"""OpenRouter Picker — gateway plugin stub.

The real work lives in:
  - desktop-plugins/openrouter-picker/plugin.js  (UI)
  - dashboard/plugin_api.py                       (API routes)

This file exists only so the gateway plugin loader finds a register()
function and stops warning.  It registers nothing.
"""


def register(ctx) -> None:
    """No-op — this plugin has no gateway-side tools or hooks."""
