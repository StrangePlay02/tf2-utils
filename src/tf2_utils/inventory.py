import math
import time

import requests

from .exceptions import InvalidInventory
from .providers.custom import Custom
from .providers.providers import PROVIDERS
from .providers.steamcommunity import SteamCommunity
from .sku import get_sku


def map_inventory(
    inventory: dict, add_skus: bool = False, skip_untradable: bool = False
) -> list[dict]:
    """Matches classids and instanceids, merges these and
    adds `sku` to each item entry if `add_skus` is enabled"""
    mapped_inventory = []

    if "assets" not in inventory:
        raise InvalidInventory("No assets found in inventory")

    for asset in inventory["assets"]:
        for desc in inventory["descriptions"]:
            if skip_untradable and not desc["tradable"]:
                continue

            if (
                asset["classid"] != desc["classid"]
                or asset["instanceid"] != desc["instanceid"]
            ):
                continue

            if add_skus:
                mapped_inventory.append({"sku": get_sku(desc), **asset, **desc})
            else:
                mapped_inventory.append({**asset, **desc})
            break

    return mapped_inventory


class Inventory:
    def __init__(
        self, provider_name: str = "steamcommunity", api_key: str = ""
    ) -> None:
        # default to steamcommunity
        self.provider = SteamCommunity()

        # default to steam if no api_key is given
        if not api_key:
            return

        provider_name = provider_name.lower()

        # if provider_name is a url, assign it as a custom provider address
        if provider_name.startswith("http"):
            self.provider = Custom(api_key, provider_name)
            return

        # loop through providers create object
        for i in PROVIDERS:
            if provider_name == i.__name__.lower():
                # set the first found provider and then stop
                self.provider = i(api_key)
                break

    def fetch(
        self,
        steam_id: str,
        app_id: int = 440,
        context_id: int = 2,
        start_assetid: str | None = None,
        page_delay: float = 3,
    ) -> dict:
        url, params = self.provider.get_url_and_params(steam_id, app_id, context_id)
        if isinstance(self.provider, SteamCommunity):
            return self._fetch_steamcommunity(url, params, start_assetid, page_delay)

        response = requests.get(url, params=params, headers=self.provider.headers)

        try:
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _fetch_steamcommunity(
        self, url: str, params: dict, start_assetid: str | None, page_delay: float
    ) -> dict:
        if not math.isfinite(page_delay) or page_delay < 0:
            raise ValueError("page_delay must be finite and nonnegative")
        if start_assetid is not None and (
            not isinstance(start_assetid, str) or not start_assetid.strip()
        ):
            raise ValueError("start_assetid must be a nonempty string")

        params = dict(params)
        seen_cursors = set()
        if start_assetid is not None:
            params["start_assetid"] = start_assetid
            seen_cursors.add(start_assetid)

        combined = {}
        assets = []
        descriptions = []
        seen_descriptions = set()
        while True:
            try:
                response = requests.get(
                    url, params=dict(params), headers=self.provider.headers
                )
            except requests.RequestException as e:
                return {"success": False, "error": str(e)}
            if not 200 <= response.status_code < 300:
                return {
                    "success": False,
                    "error": f"SteamCommunity inventory HTTP {response.status_code}",
                    "status_code": response.status_code,
                }
            try:
                page = response.json()
            except Exception as e:
                return {"success": False, "error": str(e)}

            if not isinstance(page, dict):
                return {"success": False, "error": "Invalid inventory page"}
            if not page.get("success"):
                return {
                    **page,
                    "success": False,
                    "error": page.get("error") or "Inventory page was not successful",
                }

            # Steam may omit both lists for an empty successful inventory.
            if (
                "assets" not in page
                and "descriptions" not in page
                and page.get("total_inventory_count") == 0
            ):
                page = {**page, "assets": [], "descriptions": []}
            for key, fields in (
                ("assets", ("assetid", "classid", "instanceid")),
                ("descriptions", ("classid", "instanceid")),
            ):
                entries = page.get(key)
                if not isinstance(entries, list) or any(
                    not isinstance(entry, dict)
                    or any(not isinstance(entry.get(field), str) for field in fields)
                    for entry in entries
                ):
                    return {"success": False, "error": f"Invalid inventory {key}"}

            more_items = page.get("more_items")
            if not isinstance(more_items, (bool, int, type(None))):
                return {"success": False, "error": "Invalid inventory more_items"}
            if not combined and not more_items:
                return page

            combined.update(page)
            assets.extend(page["assets"])
            for description in page["descriptions"]:
                identity = (description["classid"], description["instanceid"])
                if identity not in seen_descriptions:
                    seen_descriptions.add(identity)
                    descriptions.append(description)

            if not more_items:
                combined.update(assets=assets, descriptions=descriptions, more_items=0)
                combined.pop("last_assetid", None)
                return combined

            cursor = page.get("last_assetid")
            if not isinstance(cursor, str) or not cursor.strip():
                return {
                    "success": False,
                    "error": "Missing or invalid inventory cursor",
                }
            if cursor in seen_cursors:
                return {"success": False, "error": "Repeated inventory cursor"}
            seen_cursors.add(cursor)
            params["start_assetid"] = cursor
            if page_delay:
                time.sleep(page_delay)
