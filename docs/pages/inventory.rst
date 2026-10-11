Inventory
=========

Usage
-----

.. literalinclude:: ../usage/inventory.py
    :language: python3

``Inventory.fetch(steam_id, app_id=440, context_id=2, start_assetid=None,
page_delay=3)`` automatically follows SteamCommunity pages while ``more_items``
is true. Existing positional calls and configurable provider headers are
unchanged. ``start_assetid`` is an optional nonempty string (keep large IDs as
strings); when supplied, only the remaining pages starting at that cursor are
returned. The key is omitted from the initial request by default.

``page_delay`` must be finite and nonnegative, and specifies seconds to wait
only between pages. Set it to ``0`` to disable the delay. Invalid arguments
raise ``ValueError``. These options apply only to SteamCommunity; other providers
still make one request without Steam pagination parameters.

The returned dictionary combines all page assets (including distinct items
sharing a class) and descriptions, deduplicating descriptions by
``(classid, instanceid)`` for use with ``map_inventory``. Inventory totals and
other page metadata are retained; a completed multi-page result has
``more_items=0`` and no stale ``last_assetid``. Single-page results are unchanged,
and empty successful inventories remain valid.

Malformed pages, missing/repeated cursors, and request/JSON/application failures
return ``{"success": False, "error": ...}``, not successful partial data.
HTTP failures also include ``status_code``. HTTP 429 is returned immediately
without retries; pagination does not bypass Steam's rate limits.


.. automodule:: src.tf2_utils.inventory
    :members:
    :undoc-members:
