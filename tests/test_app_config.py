"""Unit tests for aap_ee_inspector.app_config."""

from pathlib import Path

from aap_ee_inspector.app_config import AppConfig, load_config


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

    def test_output_file_paths_are_derived_from_output_dir(self):
        config = AppConfig()
        assert config.output_file == Path("outputs/execution_environments.json")
        assert config.details_output_file == Path("outputs/execution_environment_details.json")
        assert config.report_output_file == Path("outputs/execution_environment_report.md")


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
