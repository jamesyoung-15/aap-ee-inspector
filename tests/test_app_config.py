"""Unit tests for aap_ee_inspector.app_config."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from aap_ee_inspector.app_config import (
    AppConfig,
    CacheConfig,
    OutputConfig,
    find_latest_file_in_run,
    find_latest_run_dir,
    is_run_dir_name,
    list_run_dirs,
    load_config,
)


class TestAppConfigDefaults:
    def test_default_output_dir_is_outputs(self):
        config = AppConfig()
        assert config.output.dir == Path("outputs")

    def test_default_output_fields_is_none(self):
        config = AppConfig()
        assert config.output_fields is None

    def test_default_exclusions_are_empty(self):
        config = AppConfig()
        assert config.exclusions.images == []
        assert config.exclusions.name_patterns == []

    def test_default_container_engine_is_podman(self):
        config = AppConfig()
        assert config.container.engine == "podman"

    def test_default_include_pip_packages_is_false(self):
        config = AppConfig()
        assert config.output.include_pip_packages is False

    def test_default_cache_is_remove_everything(self):
        config = AppConfig()
        assert config.cache.keep_all is False
        assert config.cache.images == []
        assert config.cache.name_patterns == []

    def test_new_run_dir_is_output_dir_slash_timestamp(self):
        config = AppConfig()
        assert config.new_run_dir("20260101T120000") == Path("outputs/20260101T120000")

    def test_latest_run_dir_is_none_when_dir_missing(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path / "does_not_exist"))
        assert config.latest_run_dir() is None

    def test_latest_output_file_is_none_when_dir_missing(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path / "does_not_exist"))
        assert config.latest_output_file() is None
        assert config.latest_details_output_file() is None

    def test_latest_run_dir_returns_most_recent_by_timestamp(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path))
        (tmp_path / "20260101T120000").mkdir()
        (tmp_path / "20260215T090000").mkdir()

        latest = config.latest_run_dir()
        assert latest is not None
        assert latest.name == "20260215T090000"

    def test_latest_output_file_returns_file_from_most_recent_run(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path))
        (tmp_path / "20260101T120000").mkdir()
        (tmp_path / "20260101T120000" / "execution_environments.json").write_text("[]")
        (tmp_path / "20260215T090000").mkdir()
        (tmp_path / "20260215T090000" / "execution_environments.json").write_text("[]")

        latest = config.latest_output_file()
        assert latest is not None
        assert latest.parent.name == "20260215T090000"

    def test_latest_details_output_file_falls_back_to_older_run(self, tmp_path):
        # Newest run only has execution_environments.json (fetch-only, no
        # inspect yet); should fall back to an older run that has details.
        config = AppConfig(output=OutputConfig(dir=tmp_path))
        (tmp_path / "20260101T120000").mkdir()
        (tmp_path / "20260101T120000" / "execution_environment_details.json").write_text("[]")
        (tmp_path / "20260215T090000").mkdir()
        (tmp_path / "20260215T090000" / "execution_environments.json").write_text("[]")

        latest_details = config.latest_details_output_file()
        assert latest_details is not None
        assert latest_details.parent.name == "20260101T120000"


class TestCacheConfigShouldKeep:
    def test_keep_all_overrides_everything(self):
        cache = CacheConfig(keep_all=True)
        assert cache.should_keep("any-image", ["any-name"])

    def test_exact_image_match_is_kept(self):
        cache = CacheConfig(images=["registry.example.com/foo:1.0"])
        assert cache.should_keep("registry.example.com/foo:1.0", ["some-name"])

    def test_image_glob_pattern_is_kept(self):
        cache = CacheConfig(images=["*/amfam_default:1.*"])
        assert cache.should_keep(
            "registry.example.com/path/amfam_default:1.21", ["amfam_default:1.21"]
        )

    def test_image_glob_pattern_no_match_is_not_kept(self):
        cache = CacheConfig(images=["*/amfam_default:1.*"])
        assert not cache.should_keep("registry.example.com/path/vmware_env:1.0", ["vmware_env:1.0"])

    def test_name_pattern_match_is_kept(self):
        cache = CacheConfig(name_patterns=["amfam_default:*"])
        assert cache.should_keep("some-image", ["amfam_default:1.21"])

    def test_no_match_is_not_kept(self):
        cache = CacheConfig(images=["other-image"], name_patterns=["other:*"])
        assert not cache.should_keep("some-image", ["some-name"])

    def test_default_config_keeps_nothing(self):
        cache = CacheConfig()
        assert not cache.should_keep("any-image", ["any-name"])

    def test_kept_if_any_of_multiple_names_matches(self):
        cache = CacheConfig(name_patterns=["EE-2"])
        assert cache.should_keep("shared-image", ["EE-1", "EE-2"])


class TestIsRunDirName:
    def test_valid_timestamp_is_a_run_dir(self):
        assert is_run_dir_name("20260101T120000")

    def test_arbitrary_string_is_not_a_run_dir(self):
        assert not is_run_dir_name("not-a-timestamp")
        assert not is_run_dir_name("foo")
        assert not is_run_dir_name("")


class TestListRunDirs:
    def test_returns_empty_list_for_missing_directory(self, tmp_path):
        assert list_run_dirs(tmp_path / "missing") == []

    def test_ignores_non_run_dir_entries(self, tmp_path):
        (tmp_path / "unrelated.txt").write_text("")
        (tmp_path / "not_a_timestamp_dir").mkdir()
        assert list_run_dirs(tmp_path) == []

    def test_sorted_oldest_to_newest(self, tmp_path):
        (tmp_path / "20261231T235959").mkdir()
        (tmp_path / "20260101T000000").mkdir()
        (tmp_path / "20260601T000000").mkdir()

        result = [p.name for p in list_run_dirs(tmp_path)]
        assert result == ["20260101T000000", "20260601T000000", "20261231T235959"]


class TestFindLatestRunDir:
    def test_returns_none_for_missing_directory(self, tmp_path):
        assert find_latest_run_dir(tmp_path / "missing") is None

    def test_picks_lexicographically_latest_match(self, tmp_path):
        (tmp_path / "20260101T000000").mkdir()
        (tmp_path / "20261231T235959").mkdir()
        (tmp_path / "20260601T000000").mkdir()

        result = find_latest_run_dir(tmp_path)
        assert result is not None
        assert result.name == "20261231T235959"


class TestFindLatestFileInRun:
    def test_returns_none_for_missing_directory(self, tmp_path):
        assert find_latest_file_in_run(tmp_path / "missing", "foo.json") is None

    def test_returns_none_when_no_run_has_the_file(self, tmp_path):
        (tmp_path / "20260101T000000").mkdir()
        assert find_latest_file_in_run(tmp_path, "foo.json") is None

    def test_picks_file_from_newest_run_that_has_it(self, tmp_path):
        (tmp_path / "20260101T000000").mkdir()
        (tmp_path / "20260101T000000" / "foo.json").write_text("")
        (tmp_path / "20260601T000000").mkdir()
        (tmp_path / "20260601T000000" / "foo.json").write_text("")

        result = find_latest_file_in_run(tmp_path, "foo.json")
        assert result is not None
        assert result.parent.name == "20260601T000000"

    def test_falls_back_to_older_run_if_newest_lacks_file(self, tmp_path):
        (tmp_path / "20260101T000000").mkdir()
        (tmp_path / "20260101T000000" / "foo.json").write_text("")
        (tmp_path / "20260601T000000").mkdir()  # newest run, but no foo.json

        result = find_latest_file_in_run(tmp_path, "foo.json")
        assert result is not None
        assert result.parent.name == "20260101T000000"


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        config = load_config(path=tmp_path / "does_not_exist.toml")
        assert config == AppConfig()

    def test_loads_output_fields_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[output]\nfields = ["name", "image"]\n')

        config = load_config(path=toml_path)
        assert config.output_fields == {"name", "image"}

    def test_loads_exclusions_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            "[exclusions]\n"
            'images = ["registry.example.com/pinned@sha256:abc"]\n'
            'name_patterns = ["rhel6_env:*"]\n'
        )

        config = load_config(path=toml_path)
        assert config.exclusions.images == ["registry.example.com/pinned@sha256:abc"]
        assert config.exclusions.name_patterns == ["rhel6_env:*"]

    def test_loads_custom_output_dir(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[output]\ndir = "custom_outputs"\n')

        config = load_config(path=toml_path)
        assert config.output.dir == Path("custom_outputs")

    def test_loads_container_engine_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[container]\nengine = "docker"\n')

        config = load_config(path=toml_path)
        assert config.container.engine == "docker"

    def test_invalid_container_engine_raises(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text('[container]\nengine = "not-a-real-engine"\n')

        with pytest.raises(ValidationError):
            load_config(path=toml_path)

    def test_loads_include_pip_packages_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text("[output]\ninclude_pip_packages = true\n")

        config = load_config(path=toml_path)
        assert config.output.include_pip_packages is True

    def test_loads_cache_config_from_toml(self, tmp_path):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            "[cache]\n"
            "keep_all = true\n"
            'images = ["registry.example.com/pinned:1.0"]\n'
            'name_patterns = ["amfam_default:*"]\n'
        )

        config = load_config(path=toml_path)
        assert config.cache.keep_all is True
        assert config.cache.images == ["registry.example.com/pinned:1.0"]
        assert config.cache.name_patterns == ["amfam_default:*"]
