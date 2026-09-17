"""Unit tests for aap_ee_inspector.app_config."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from aap_ee_inspector.app_config import (
    AppConfig,
    CacheConfig,
    OutputConfig,
    find_latest_file,
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

    def test_new_output_file_paths_include_timestamp(self):
        config = AppConfig()
        assert config.new_output_file("20260101T120000") == Path(
            "outputs/20260101T120000_execution_environments.json"
        )
        assert config.new_details_output_file("20260101T120000") == Path(
            "outputs/20260101T120000_execution_environment_details.json"
        )
        assert config.new_report_output_file("20260101T120000") == Path(
            "outputs/20260101T120000_execution_environment_report.md"
        )

    def test_latest_output_file_is_none_when_dir_missing(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path / "does_not_exist"))
        assert config.latest_output_file() is None
        assert config.latest_details_output_file() is None

    def test_latest_output_file_returns_most_recent_by_timestamp(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path))
        (tmp_path / "20260101T120000_execution_environments.json").write_text("[]")
        (tmp_path / "20260215T090000_execution_environments.json").write_text("[]")

        latest = config.latest_output_file()
        assert latest is not None
        assert latest.name == "20260215T090000_execution_environments.json"


class TestCacheConfigShouldKeep:
    def test_keep_all_overrides_everything(self):
        cache = CacheConfig(keep_all=True)
        assert cache.should_keep("any-image", ["any-name"])

    def test_exact_image_match_is_kept(self):
        cache = CacheConfig(images=["registry.example.com/foo:1.0"])
        assert cache.should_keep("registry.example.com/foo:1.0", ["some-name"])

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


class TestFindLatestFile:
    def test_returns_none_for_missing_directory(self, tmp_path):
        assert find_latest_file(tmp_path / "missing", "foo.json") is None

    def test_returns_none_when_no_files_match(self, tmp_path):
        (tmp_path / "unrelated.txt").write_text("")
        assert find_latest_file(tmp_path, "foo.json") is None

    def test_picks_lexicographically_latest_match(self, tmp_path):
        (tmp_path / "20260101T000000_foo.json").write_text("")
        (tmp_path / "20261231T235959_foo.json").write_text("")
        (tmp_path / "20260601T000000_foo.json").write_text("")

        result = find_latest_file(tmp_path, "foo.json")
        assert result is not None
        assert result.name == "20261231T235959_foo.json"


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
