from shared.categories import canonical_category_from_raw, canonical_category_from_slug


def test_canonical_category_from_slug_handles_aliases():
    direct = canonical_category_from_slug("Politics")
    assert direct == ("politics", "Politics")

    alias = canonical_category_from_slug("us-politics")
    assert alias == ("politics", "Politics")


def test_canonical_category_from_raw_matches_keywords():
    inferred = canonical_category_from_raw("CFB 2025")
    assert inferred == ("sports", "Sports")


def test_canonical_category_from_raw_uses_tags():
    tagged = canonical_category_from_raw(None, tags=["Macro", "Crypto"])
    assert tagged == ("crypto", "Crypto")
