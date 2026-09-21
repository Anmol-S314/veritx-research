from veritx_dse.core.artifact import canonical_json,content_id


def test_canonical_json_order():
    assert canonical_json({"b":2,"a":1})=='{"a":1,"b":2}'


def test_domains_separate_ids():
    assert content_id("a",{"x":1})!=content_id("b",{"x":1})
