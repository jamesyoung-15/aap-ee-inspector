"""Unit tests for aap_ee_inspector.filters."""

from aap_ee_inspector.filters import matches_any, parse_csv_patterns


class TestMatchesAny:
    def test_exact_match(self):
        assert matches_any("amfam_default:1.21", ["amfam_default:1.21"])

    def test_glob_match(self):
        assert matches_any("vmware_env:latest", ["vmware_env:*"])

    def test_no_match(self):
        assert not matches_any("amfam_default:1.21", ["vmware_env:*"])

    def test_matches_any_of_multiple_patterns(self):
        patterns = ["ens_env:*", "amfam_default:1.1"]
        assert matches_any("amfam_default:1.1", patterns)
        assert matches_any("ens_env:latest", patterns)
        assert not matches_any("rhel6_env:1.0", patterns)

    def test_empty_patterns_never_matches(self):
        assert not matches_any("anything", [])

    def test_case_sensitive(self):
        # fnmatch is case-sensitive on POSIX systems by default.
        assert not matches_any("Default execution environment", ["default*"])
        assert matches_any("Default execution environment", ["Default*"])


class TestParseCsvPatterns:
    def test_none_returns_none(self):
        assert parse_csv_patterns(None) is None

    def test_single_pattern(self):
        assert parse_csv_patterns("vmware_env:*") == ["vmware_env:*"]

    def test_multiple_patterns_split_on_comma(self):
        result = parse_csv_patterns("amfam_default:1.21,vmware_env:*")
        assert result == ["amfam_default:1.21", "vmware_env:*"]

    def test_strips_whitespace_around_patterns(self):
        result = parse_csv_patterns(" amfam_default:1.21 , vmware_env:* ")
        assert result == ["amfam_default:1.21", "vmware_env:*"]

    def test_empty_string_returns_empty_list(self):
        assert parse_csv_patterns("") == []

    def test_drops_empty_entries_from_trailing_commas(self):
        assert parse_csv_patterns("a,,b,") == ["a", "b"]
