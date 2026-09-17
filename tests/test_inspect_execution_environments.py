"""Unit tests for aap_ee_inspector.inspect_execution_environments.

Only pure/file-based logic is covered here (parsing, filtering); actual
podman pull/run subprocess calls are exercised manually/ad-hoc against real
images rather than mocked in unit tests.
"""

import json

import pytest

from aap_ee_inspector.app_config import AppConfig, ExclusionsConfig, OutputConfig
from aap_ee_inspector.inspect_execution_environments import (
    is_excluded,
    load_images,
    parse_ansible_version_block,
    parse_collections_block,
    parse_pip_list_block,
    resolve_input_file,
)

SAMPLE_ANSIBLE_VERSION_OUTPUT = """ansible [core 2.16.17]
  config file = None
  configured module search path = ['/runner/.ansible/plugins/modules']
  ansible python module location = /usr/local/lib/python3.12/site-packages/ansible
  ansible collection location = /runner/.ansible/collections
  executable location = /usr/local/bin/ansible
  python version = 3.12.12 (main, Jan 19 2026, 00:00:00) [GCC 11.5.0]
  jinja version = 3.1.6
  libyaml = True
"""

SAMPLE_COLLECTIONS_JSON = json.dumps(
    {
        "/usr/share/ansible/collections/ansible_collections": {
            "amazon.aws": {"version": "9.5.1"},
            "community.vmware": {"version": "6.2.0"},
        }
    }
)


class TestParseAnsibleVersionBlock:
    def test_extracts_all_three_versions(self):
        core, python, jinja = parse_ansible_version_block(SAMPLE_ANSIBLE_VERSION_OUTPUT)
        assert core == "2.16.17"
        assert python == "3.12.12"
        assert jinja == "3.1.6"

    def test_missing_fields_return_none(self):
        core, python, jinja = parse_ansible_version_block("not ansible output at all")
        assert core is None
        assert python is None
        assert jinja is None

    def test_ignores_warning_lines_before_version_block(self):
        text = "WARNING: image platform mismatch\n" + SAMPLE_ANSIBLE_VERSION_OUTPUT
        core, python, jinja = parse_ansible_version_block(text)
        assert core == "2.16.17"
        assert python == "3.12.12"
        assert jinja == "3.1.6"


class TestParseCollectionsBlock:
    def test_flattens_single_path_to_name_version_dict(self):
        collections = parse_collections_block(SAMPLE_COLLECTIONS_JSON)
        assert collections == {"amazon.aws": "9.5.1", "community.vmware": "6.2.0"}

    def test_flattens_multiple_paths_into_one_dict(self):
        text = json.dumps(
            {
                "/path/one": {"a.b": {"version": "1.0.0"}},
                "/path/two": {"c.d": {"version": "2.0.0"}},
            }
        )
        collections = parse_collections_block(text)
        assert collections == {"a.b": "1.0.0", "c.d": "2.0.0"}

    def test_no_json_object_returns_empty_dict(self):
        assert parse_collections_block("no json here") == {}

    def test_skips_warning_text_before_json(self):
        text = "WARNING: some galaxy warning\n" + SAMPLE_COLLECTIONS_JSON
        collections = parse_collections_block(text)
        assert collections == {"amazon.aws": "9.5.1", "community.vmware": "6.2.0"}


SAMPLE_PIP_LIST_JSON = json.dumps(
    [
        {"name": "certifi", "version": "2026.7.22"},
        {"name": "cryptography", "version": "50.0.1"},
    ]
)


class TestParsePipListBlock:
    def test_flattens_list_to_name_version_dict(self):
        packages = parse_pip_list_block(SAMPLE_PIP_LIST_JSON)
        assert packages == {"certifi": "2026.7.22", "cryptography": "50.0.1"}

    def test_no_json_array_returns_empty_dict(self):
        assert parse_pip_list_block("no json here") == {}

    def test_skips_warning_text_before_json(self):
        text = "WARNING: pip warning\n" + SAMPLE_PIP_LIST_JSON
        packages = parse_pip_list_block(text)
        assert packages == {"certifi": "2026.7.22", "cryptography": "50.0.1"}

    def test_empty_list_returns_empty_dict(self):
        assert parse_pip_list_block("[]") == {}


class TestIsExcluded:
    def test_excluded_by_exact_image_match(self):
        exclusions = ExclusionsConfig(images=["registry.example.com/foo:1.0"])
        assert is_excluded("registry.example.com/foo:1.0", "any-name", exclusions)

    def test_excluded_by_name_pattern(self):
        exclusions = ExclusionsConfig(name_patterns=["rhel6_env:*"])
        assert is_excluded("some-image", "rhel6_env:1.0", exclusions)

    def test_not_excluded_when_no_match(self):
        exclusions = ExclusionsConfig(images=["other-image"], name_patterns=["other:*"])
        assert not is_excluded("some-image", "some-name", exclusions)

    def test_no_exclusions_configured_never_excludes(self):
        assert not is_excluded("any-image", "any-name", ExclusionsConfig())


class TestLoadImages:
    def _write_records_file(self, tmp_path, records, filename="input.json"):
        path = tmp_path / filename
        path.write_text(json.dumps(records))
        return path

    def test_groups_names_by_image(self, tmp_path):
        path = self._write_records_file(
            tmp_path,
            [
                {"name": "EE-A", "image": "shared-image"},
                {"name": "EE-B", "image": "shared-image"},
                {"name": "EE-C", "image": "other-image"},
            ],
        )
        images = load_images(path, AppConfig())
        assert images == {
            "shared-image": ["EE-A", "EE-B"],
            "other-image": ["EE-C"],
        }

    def test_applies_config_exclusions(self, tmp_path):
        path = self._write_records_file(
            tmp_path,
            [
                {"name": "keep-me", "image": "img-1"},
                {"name": "rhel6_env:1.0", "image": "img-2"},
            ],
        )
        config = AppConfig(exclusions=ExclusionsConfig(name_patterns=["rhel6_env:*"]))

        images = load_images(path, config)
        assert images == {"img-1": ["keep-me"]}

    def test_only_narrows_after_exclusions(self, tmp_path):
        path = self._write_records_file(
            tmp_path,
            [
                {"name": "vmware_env:1.0", "image": "img-1"},
                {"name": "amfam_default:1.1", "image": "img-2"},
            ],
        )
        images = load_images(path, AppConfig(), only=["vmware_env:*"])
        assert images == {"img-1": ["vmware_env:1.0"]}


class TestResolveInputFile:
    def test_raises_if_nothing_found_and_no_explicit_path(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path / "outputs"))
        with pytest.raises(FileNotFoundError):
            resolve_input_file(config, explicit_path=None)

    def test_raises_if_explicit_path_missing(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path))
        with pytest.raises(FileNotFoundError):
            resolve_input_file(config, explicit_path=str(tmp_path / "nope.json"))

    def test_explicit_path_takes_precedence_over_latest(self, tmp_path):
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()
        (output_dir / "20260101T000000_execution_environments.json").write_text("[]")
        explicit = tmp_path / "custom.json"
        explicit.write_text("[]")

        config = AppConfig(output=OutputConfig(dir=output_dir))
        result = resolve_input_file(config, explicit_path=str(explicit))
        assert result == explicit

    def test_picks_latest_when_no_explicit_path(self, tmp_path):
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()
        (output_dir / "20260101T000000_execution_environments.json").write_text("[]")
        (output_dir / "20260601T000000_execution_environments.json").write_text("[]")

        config = AppConfig(output=OutputConfig(dir=output_dir))
        result = resolve_input_file(config, explicit_path=None)
        assert result.name == "20260601T000000_execution_environments.json"
