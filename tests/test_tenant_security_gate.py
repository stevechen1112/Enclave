from scripts.tenant_security_gate import ForeignKeyEdge, discover_inherited_tables


def test_discovers_recursive_non_null_fk_ownership() -> None:
    edges = [
        ForeignKeyEdge("messages", "conversation_id", "conversations", "id", False),
        ForeignKeyEdge("message_reviews", "message_id", "messages", "id", False),
    ]

    result = discover_inherited_tables({"conversations"}, {"tenants"}, edges)

    assert set(result) == {"messages", "message_reviews"}


def test_nullable_fk_does_not_implicitly_claim_tenant_ownership() -> None:
    edges = [
        ForeignKeyEdge("optional_links", "document_id", "documents", "id", True),
    ]

    result = discover_inherited_tables({"documents"}, {"tenants"}, edges)

    assert result == {}
