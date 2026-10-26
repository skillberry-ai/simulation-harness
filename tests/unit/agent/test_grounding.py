"""Tests for the strict-fidelity grounding checker."""

from typing import Any

from simulation_harness.agent.grounding import (
    Ungrounded,
    check_grounding,
    collect_strings,
    static_evidence,
)

STORE: dict[str, list[dict[str, Any]]] = {
    "files": [
        {
            "file_id": "f1",
            "owner": "acme",
            "repo": "infra",
            "ref": "main",
            "path": "roles/ocp4/tasks/main.yml",
        }
    ],
    "instances": [{"instance_id": "i-0abc", "az": "ap-south-1a"}],
}


def _check(
    response: Any, request: dict[str, Any] | None = None, static: str = ""
) -> list[Ungrounded]:
    return check_grounding(response, request or {}, STORE, static)


def test_copied_row_values_are_grounded() -> None:
    assert _check({"owner": "acme", "path": "roles/ocp4/tasks/main.yml"}) == []


def test_invented_match_paths_are_flagged() -> None:
    """The measured parsec failure: one seeded file, several invented paths."""
    response = {
        "matches": [
            {"path": "roles/ocp4/tasks/main.yml"},
            {"path": "roles/ocp4/defaults/main.yml"},
            {"path": "playbooks/deploy.yml"},
        ],
        "total_matches": 3,
        "truncated": False,
    }
    assert _check(response) == [
        Ungrounded("$.matches[1].path", "roles/ocp4/defaults/main.yml"),
        Ungrounded("$.matches[2].path", "playbooks/deploy.yml"),
    ]


def test_derived_substring_is_grounded() -> None:
    assert _check({"region": "ap-south-1"}) == []


def test_request_echo_is_grounded() -> None:
    assert _check({"next": "zz-cursor-9"}, request={"cursor": "zz-cursor-9"}) == []


def test_templated_message_is_grounded_by_static_text() -> None:
    static = "No catalog item matching '<name>' found in any agnosticv repo."
    value = "No catalog item matching 'clusterplatform.x' found in any agnosticv repo."
    flagged = _check(
        {"message": value}, request={"name": "clusterplatform.x"}, static=static
    )
    assert flagged == []


def test_url_composed_from_row_fields_is_grounded() -> None:
    static = "https://github.com/<owner>/<repo>/blob/<ref>/<path>"
    url = "https://github.com/acme/infra/blob/main/roles/ocp4/tasks/main.yml"
    assert _check({"url": url}, static=static) == []


def test_enum_value_from_static_text_is_grounded() -> None:
    assert _check({"state": "merged"}, static="open | closed | merged") == []


def test_non_strings_empty_and_timestamps_are_exempt() -> None:
    response = {
        "count": 7,
        "ok": True,
        "missing": None,
        "blank": "",
        "at": "2026-10-09T12:00:00Z",
        "on": "2026-10-09",
    }
    assert _check(response) == []


def test_keys_are_not_checked() -> None:
    assert _check({"wholly_invented_key": "acme"}) == []


def test_error_envelope_is_exempt() -> None:
    assert _check({"error": "Restaurant 'zz' not found"}) == []


def test_error_envelope_exemption_is_top_level_only() -> None:
    flagged = _check({"items": [{"error": "invented row text"}]})
    assert flagged == [Ungrounded("$.items[0].error", "invented row text")]


def test_top_level_list_response_paths() -> None:
    assert _check(["acme", "Zyxwv"]) == [Ungrounded("$[1]", "Zyxwv")]


def test_model_written_miss_message_is_grounded() -> None:
    """parsec-github lookup_catalog_item: the miss contract's message is prose."""
    response = {
        "found": False,
        "similar_items": [],
        "message": "No catalog item matches 'frobnicator'. The index is complete; "
        "do not search further.",
    }
    assert _check(response, request={"name": "frobnicator"}) == []


def test_invented_identifier_inside_prose_is_flagged() -> None:
    message = "Found instance i-0zzz9 running in the requested account today."
    assert _check({"message": message}) == [Ungrounded("$.message", message)]


def test_short_invented_name_is_still_flagged() -> None:
    assert _check({"name": "Zyxwv Bistro"}) == [Ungrounded("$.name", "Zyxwv Bistro")]


def test_collect_strings_ignores_keys_and_non_strings() -> None:
    assert collect_strings({"k": ["a", {"j": "b"}, 3, None]}) == {"a", "b"}


def test_static_evidence_unescapes_spec_strings() -> None:
    api = {"info": {"description": 'A "quoted" dash — here'}}
    text = static_evidence(api, "# Skill\n")
    assert 'A "quoted" dash — here' in text
    assert "# Skill" in text


def test_ungrounded_as_dict() -> None:
    assert Ungrounded("$.a", "x").as_dict() == {"path": "$.a", "value": "x"}
