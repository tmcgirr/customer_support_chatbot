from app.core import ids


def test_prefixes_match_contract() -> None:
    assert ids.conversation_id().startswith("cnv_")
    assert ids.message_id().startswith("msg_")
    assert ids.run_id().startswith("run_")
    assert ids.request_id().startswith("req_")
    assert ids.canonical_answer_id().startswith("can_")
    assert ids.log_request_id().startswith("rid_")


def test_ids_are_unique() -> None:
    generated = {ids.conversation_id() for _ in range(1000)}
    assert len(generated) == 1000


def test_ulids_sort_by_creation_order() -> None:
    ordered = [ids.message_id() for _ in range(50)]
    assert ordered == sorted(ordered)
