from scripts.release_identity import migration_heads, route_contract


def test_release_identity_has_exactly_one_schema_head():
    heads = migration_heads()
    assert len(heads) == 1
    assert heads[0]


def test_release_route_contract_is_unique_and_hashable():
    routes, contract_hash = route_contract()
    assert len(routes) == len(set(routes))
    assert "/knowledge/assets" in routes
    assert len(contract_hash) == 64
