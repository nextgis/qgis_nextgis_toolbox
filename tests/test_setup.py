from setup import remove_commit_hashes


def test_remove_commit_hashes_removes_nested_hashes() -> None:
    payload = {
        "commit_hash": "top-level",
        "nested": {
            "commit_hash": "nested",
            "value": "preserved",
        },
        "items": [
            {"commit_hash": "list-item", "name": "preserved"},
        ],
    }

    assert remove_commit_hashes(payload) == {
        "nested": {"value": "preserved"},
        "items": [{"name": "preserved"}],
    }
