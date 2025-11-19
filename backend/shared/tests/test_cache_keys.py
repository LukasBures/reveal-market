from shared import cache_keys


def test_category_cache_key_slugifies_hyphenated_input():
    key = cache_keys.category_cache_key("AI & Tech", 18, 5)
    assert key == "markets:category:ai-tech|limit=18|offset=5"


def test_suggest_cache_key_handles_whitespace():
    key = cache_keys.suggest_cache_key("  Alpha Query  ", 3)
    assert key == "markets:suggest:alpha query|limit=3"


def test_resolution_cache_key_lowercases_condition():
    key = cache_keys.resolution_cache_key("0xABCDEF")
    assert key == "markets:resolution:0xabcdef"
