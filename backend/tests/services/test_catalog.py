from app.services.catalog import (
    apply_catalog_order,
    catalog_chart_keys,
    insert_chart_before,
    is_song_chart,
    song_chart_groups,
    sorted_catalog_charts,
)


def test_drops_mv_and_unplayable() -> None:
    groups = [
        {
            "name": "巅峰榜",
            "charts": [
                {"key": "26", "name": "热歌榜", "playable": True},
                {"key": "201", "name": "MV榜", "playable": True},
                {"key": "4", "name": "流行指数榜", "playable": False},
            ],
        },
        {"name": "视频", "charts": [{"key": "9", "name": "视频榜", "playable": True}]},
    ]
    out = song_chart_groups(groups)
    assert out == [
        {
            "name": "巅峰榜",
            "charts": [{"key": "26", "name": "热歌榜", "playable": True}],
        }
    ]


def test_keeps_song_charts() -> None:
    assert is_song_chart(key="26", name="热歌榜")
    assert is_song_chart(key="60", name="抖音热歌榜")
    assert not is_song_chart(key="201", name="MV榜")
    assert not is_song_chart(key="1", name="歌手榜")


_GROUPS = [
    {
        "name": "巅峰榜",
        "charts": [
            {"key": "4", "name": "流行指数榜", "playable": True},
            {"key": "26", "name": "热歌榜", "playable": True},
            {"key": "27", "name": "新歌榜", "playable": True},
        ],
    },
    {
        "name": "地区榜",
        "charts": [{"key": "5", "name": "内地榜", "playable": True}],
    },
]


def test_catalog_order_defaults_to_official() -> None:
    keys = catalog_chart_keys(_GROUPS, {})
    assert keys == ["4", "26", "27", "5"]
    items = sorted_catalog_charts(_GROUPS, {})
    assert [item["sort_order"] for item in items] == [10, 20, 30, 40]


def test_catalog_order_cross_group() -> None:
    order = {"26": 10, "5": 20, "4": 30, "27": 40}
    keys = catalog_chart_keys(_GROUPS, order)
    assert keys == ["26", "5", "4", "27"]
    applied = apply_catalog_order(_GROUPS, order)
    by_key = {
        chart["key"]: chart["sort_order"]
        for group in applied
        for chart in group["charts"]
    }
    assert by_key["26"] == 10
    assert by_key["5"] == 20


def test_new_charts_append_after_saved_order() -> None:
    keys = catalog_chart_keys(_GROUPS, {"26": 10, "4": 20})
    assert keys[:2] == ["26", "4"]
    assert set(keys[2:]) == {"27", "5"}


def test_insert_chart_before_moves_to_slot() -> None:
    keys = ["4", "26", "27", "5"]
    assert insert_chart_before(keys, "5", "26") == ["4", "5", "26", "27"]
    assert insert_chart_before(keys, "4", None) == ["26", "27", "5", "4"]
    assert insert_chart_before(keys, "26", "26") == keys
    assert insert_chart_before(keys, "999", "26") is None
    assert insert_chart_before(keys, "26", "nope") is None

