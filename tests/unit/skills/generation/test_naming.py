from simulation_harness.skills.generation.naming import (
    _force_skill_name,
    sanitize_skill_name,
)


class TestSanitizeSkillName:
    """Skill names must satisfy the Agent Skills specification:
    1-64 chars, lowercase alphanumeric and single hyphens only, no leading,
    trailing, or consecutive hyphens.
    """

    def test_lowercases(self) -> None:
        assert sanitize_skill_name("MyAPI") == "myapi"

    def test_spaces_become_single_hyphen(self) -> None:
        assert sanitize_skill_name("My Cool API") == "my-cool-api"

    def test_dots_are_replaced(self) -> None:
        # The reported regression: "Booking.com Demand API".
        assert sanitize_skill_name("Booking.com Demand API") == "booking-com-demand-api"

    def test_collapses_consecutive_separators(self) -> None:
        assert sanitize_skill_name("a  --  b") == "a-b"

    def test_strips_leading_and_trailing_separators(self) -> None:
        assert sanitize_skill_name("  .API. ") == "api"

    def test_already_valid_unchanged(self) -> None:
        assert sanitize_skill_name("booking-demand-api") == "booking-demand-api"

    def test_caps_at_64_chars_without_trailing_hyphen(self) -> None:
        result = sanitize_skill_name("a" * 70)
        assert len(result) == 64
        assert not result.endswith("-")

    def test_cap_does_not_leave_trailing_hyphen(self) -> None:
        # A separator landing exactly on the boundary must be trimmed.
        raw = "a" * 63 + " bcd"
        result = sanitize_skill_name(raw)
        assert len(result) <= 64
        assert not result.endswith("-")

    def test_empty_falls_back(self) -> None:
        assert sanitize_skill_name("") == "simulation"

    def test_all_invalid_falls_back(self) -> None:
        assert sanitize_skill_name("...///...") == "simulation"

    def test_digits_preserved(self) -> None:
        assert sanitize_skill_name("api-v2") == "api-v2"


class TestForceSkillName:
    def test_inserts_frontmatter_when_missing(self) -> None:
        out = _force_skill_name("body text", "my-skill")
        assert out.startswith("---\nname: my-skill\n---")
