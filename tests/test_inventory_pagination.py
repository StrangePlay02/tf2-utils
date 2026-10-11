from unittest.mock import Mock, patch

import pytest
import requests

from src.tf2_utils.inventory import Inventory, map_inventory


@pytest.fixture
def transport():
    with (
        patch("src.tf2_utils.inventory.requests.get") as get,
        patch("src.tf2_utils.inventory.time.sleep") as sleep,
    ):
        yield get, sleep


def page(assetid="item-1", instanceid="0", **metadata):
    return {
        "success": 1,
        "assets": [
            {"assetid": assetid, "classid": "shared-class", "instanceid": instanceid}
        ],
        "descriptions": [{"classid": "shared-class", "instanceid": instanceid}],
        **metadata,
    }


def response(data, status_code=200):
    result = Mock(status_code=status_code)
    result.json.return_value = data
    return result


@pytest.mark.parametrize("more_items", [None, 0, False])
def test_single_page_is_unchanged(transport, more_items):
    get, sleep = transport
    data = page(last_assetid="not-a-continuation")
    if more_items is not None:
        data["more_items"] = more_items
    get.return_value = response(data)

    assert Inventory().fetch("test-user") is data
    get.assert_called_once()
    assert get.call_args.kwargs["params"] == {"l": "english", "count": 2500}
    sleep.assert_not_called()


def test_initial_cursor_on_single_page(transport):
    get, sleep = transport
    data = page()
    get.return_value = response(data)

    assert Inventory().fetch("test-user", start_assetid="18446744073709551615") is data
    assert get.call_args.kwargs["params"] == {
        "l": "english",
        "count": 2500,
        "start_assetid": "18446744073709551615",
    }
    get.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("page_count", [2, 3])
@pytest.mark.parametrize("initial_cursor", [None, "18446744073709551615"])
def test_pagination_combines_remaining_pages(transport, page_count, initial_cursor):
    get, sleep = transport
    pages = [
        page(
            assetid=f"item-{i}",
            instanceid=str(i % 2),
            more_items=int(i < page_count - 1),
            last_assetid=f"opaque-cursor-{i}",
        )
        for i in range(page_count)
    ]
    pages[0].update(total_inventory_count=100, rwgrsn=-2)
    get.side_effect = [response(data) for data in pages]
    inventory = Inventory()
    inventory.provider.headers["user-agent"] = "test-agent"
    inventory.provider.headers["X-Test"] = "preserved"

    result = inventory.fetch("test-user", 730, 3, initial_cursor)

    assert result["assets"] == [data["assets"][0] for data in pages]
    assert result["descriptions"] == [
        pages[0]["descriptions"][0],
        pages[1]["descriptions"][0],
    ]
    assert len(map_inventory(result)) == page_count
    assert result["total_inventory_count"] == 100
    assert result["rwgrsn"] == -2
    assert result["success"] == 1
    assert result["more_items"] == 0
    assert "last_assetid" not in result
    assert get.call_count == page_count
    assert sleep.call_count == page_count - 1
    assert all(call.args == (3,) for call in sleep.call_args_list)
    for i, call in enumerate(get.call_args_list):
        expected_params = {"l": "english", "count": 2500}
        if i:
            expected_params["start_assetid"] = f"opaque-cursor-{i - 1}"
        elif initial_cursor is not None:
            expected_params["start_assetid"] = initial_cursor
        assert call.args == ("https://steamcommunity.com/inventory/test-user/730/3",)
        assert call.kwargs["params"] == expected_params
        assert call.kwargs["headers"] == inventory.provider.headers
        assert call.kwargs["headers"]["User-Agent"] == "test-agent"
        assert call.kwargs["headers"]["X-Test"] == "preserved"
        assert call.kwargs["headers"]["Referer"] == (
            "https://steamcommunity.com/profiles/test-user/inventory"
        )


@pytest.mark.parametrize("omit_lists", [False, True])
def test_empty_inventory(transport, omit_lists):
    get, sleep = transport
    data = {"success": 1, "total_inventory_count": 0}
    if not omit_lists:
        data.update(assets=[], descriptions=[])
    get.return_value = response(data)

    result = Inventory().fetch("test-user")

    assert result["success"] == 1
    assert result["assets"] == result["descriptions"] == []
    assert map_inventory(result) == []
    get.assert_called_once()
    sleep.assert_not_called()


def test_empty_final_page_and_description_identity(transport):
    get, sleep = transport
    first = page(more_items=1, last_assetid="a", total_inventory_count=2)
    second = page("item-2", more_items=1, last_assetid="b")
    second["assets"][0]["classid"] = "another-class"
    second["descriptions"][0]["classid"] = "another-class"
    get.side_effect = [
        response(first),
        response(second),
        response({"success": 1, "assets": [], "descriptions": []}),
    ]

    result = Inventory().fetch("test-user")

    assert result["assets"] == first["assets"] + second["assets"]
    assert result["descriptions"] == first["descriptions"] + second["descriptions"]
    assert len(map_inventory(result)) == 2
    assert result["total_inventory_count"] == 2
    assert result["more_items"] == 0
    assert "last_assetid" not in result
    assert get.call_count == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize("cursor", [None, "", " ", 123, 1.5, []])
def test_missing_or_invalid_next_cursor(transport, cursor):
    get, sleep = transport
    data = page(more_items=1)
    if cursor is not None:
        data["last_assetid"] = cursor
    get.return_value = response(data)

    result = Inventory().fetch("test-user")

    assert result["success"] is False
    assert "cursor" in result["error"]
    get.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("cursors", [("a", "a"), ("a", "b", "a")])
def test_repeated_cursor_and_cycles(transport, cursors):
    get, sleep = transport
    get.side_effect = [
        response(page(more_items=1, last_assetid=cursor)) for cursor in cursors
    ]

    result = Inventory().fetch("test-user")

    assert result == {"success": False, "error": "Repeated inventory cursor"}
    assert get.call_count == len(cursors)
    assert sleep.call_count == len(cursors) - 1


def test_cursor_equal_to_initial_cursor(transport):
    get, sleep = transport
    get.return_value = response(page(more_items=1, last_assetid="opaque"))

    assert Inventory().fetch("test-user", start_assetid="opaque")["success"] is False
    get.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        None,
        {"success": 1},
        page(assets=None),
        page(descriptions={}),
        page(assets=[None]),
        page(assets=[{"assetid": "item"}]),
        page(descriptions=[{"classid": []}]),
        page(more_items="0"),
    ],
)
@pytest.mark.parametrize("later_page", [False, True])
def test_invalid_page_structures(transport, invalid, later_page):
    get, sleep = transport
    responses = [response(invalid)]
    if later_page:
        responses.insert(0, response(page(more_items=1, last_assetid="next")))
    get.side_effect = responses

    result = Inventory().fetch("test-user")

    assert result["success"] is False
    assert "Invalid inventory" in result["error"]
    assert get.call_count == len(responses)
    assert sleep.call_count == int(later_page)


@pytest.mark.parametrize("failure", ["json", "application", "http", "429", "network"])
@pytest.mark.parametrize("later_page", [False, True])
def test_page_failures_are_explicit_without_retry(transport, failure, later_page):
    get, sleep = transport
    failed = response({"success": 0, "error": "inventory unavailable"})
    if failure == "json":
        failed.json.side_effect = ValueError("invalid JSON")
    elif failure in ("http", "429"):
        failed.status_code = 503 if failure == "http" else 429
    elif failure == "network":
        failed = requests.ConnectionError("connection failed")
    responses = [failed]
    if later_page:
        responses.insert(0, response(page(more_items=1, last_assetid="next")))
    get.side_effect = responses

    result = Inventory().fetch("test-user")

    assert result["success"] is False
    assert result["error"]
    assert "assets" not in result
    if failure in ("http", "429"):
        assert result["status_code"] == failed.status_code
        assert str(failed.status_code) in result["error"]
        failed.json.assert_not_called()
    assert get.call_count == len(responses)
    assert sleep.call_count == int(later_page)


@pytest.mark.parametrize("delay", [0, 0.25])
def test_configurable_delay(transport, delay):
    get, sleep = transport
    get.side_effect = [
        response(page(more_items=1, last_assetid="next")),
        response(page("item-2")),
    ]

    assert Inventory().fetch("test-user", page_delay=delay)["success"] == 1
    if delay:
        sleep.assert_called_once_with(delay)
    else:
        sleep.assert_not_called()


@pytest.mark.parametrize("delay", [-1, float("inf"), float("nan")])
def test_invalid_delay(transport, delay):
    get, sleep = transport
    with pytest.raises(ValueError, match="page_delay"):
        Inventory().fetch("test-user", page_delay=delay)
    get.assert_not_called()
    sleep.assert_not_called()


@pytest.mark.parametrize("cursor", ["", " ", 123, 1.5])
def test_invalid_initial_cursor(transport, cursor):
    get, sleep = transport
    with pytest.raises(ValueError, match="start_assetid"):
        Inventory().fetch("test-user", start_assetid=cursor)
    get.assert_not_called()
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "provider_name", ["expressload", "steamsupply", "steamapis", "https://example.com"]
)
def test_other_providers_are_single_request(transport, provider_name):
    get, sleep = transport
    inventory = Inventory(provider_name, "test-key")
    url, params = inventory.provider.get_url_and_params("test-user", 440, 2)
    data = page(more_items=1, last_assetid="ignored")
    get.return_value = response(data)

    assert inventory.fetch("test-user", 440, 2, "ignored", 0) is data
    get.assert_called_once_with(url, params=params, headers=inventory.provider.headers)
    assert "start_assetid" not in get.call_args.kwargs["params"]
    sleep.assert_not_called()
