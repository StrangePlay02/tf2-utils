from requests.structures import CaseInsensitiveDict

from .provider import Provider


class SteamCommunity(Provider):
    def __init__(self, api_key: str = "") -> None:
        super().__init__(api_key)
        self.headers = CaseInsensitiveDict(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                )
            }
        )

    def get_url_and_params(
        self, steam_id: str, app_id: int, context_id: int
    ) -> tuple[str, dict]:
        self.headers["Referer"] = (
            f"https://steamcommunity.com/profiles/{steam_id}/inventory"
        )
        return (
            f"https://steamcommunity.com/inventory/{steam_id}/{app_id}/{context_id}",
            {"l": "english", "count": 2500},
        )
