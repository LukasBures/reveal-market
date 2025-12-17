from shared import cache_keys


def test_category_cache_key_slugifies_hyphenated_input():
    key = cache_keys.category_cache_key("AI & Tech", 18, 5)
    assert key == "v1:markets:category:ai-tech|limit=18|offset=5"


def test_category_cache_key_respects_order_by():
    key = cache_keys.category_cache_key("sports", 10, 0, order_by="volume")
    assert key == "v1:markets:category:sports|limit=10|offset=0|order_by=volume"


def test_suggest_cache_key_handles_whitespace():
    key = cache_keys.suggest_cache_key("  Alpha Query  ", 3)
    assert key == "v1:markets:suggest:alpha query|limit=3"


def test_resolution_cache_key_lowercases_condition():
    key = cache_keys.resolution_cache_key("0xABCDEF")
    assert key == "v1:markets:resolution:0xabcdef"


def test_markets_list_cache_key_versioned_and_normalized():
    key = cache_keys.markets_list_cache_key("commit", None, None, "My Search", 10, 0)
    assert key.startswith("v1:markets:list:")
    assert "status=commit" in key
    assert "search=my search" in key


def test_proof_receipt_cache_key_prefixed():
    key = cache_keys.proof_receipt_cache_key("0xabc")
    assert key.startswith("v1:proofs:receipt:")
