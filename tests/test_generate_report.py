"""Unit tests for aap_ee_inspector.generate_report."""

import json

import pytest

from aap_ee_inspector.app_config import AppConfig, OutputConfig
from aap_ee_inspector.generate_report import (
    load_details,
    render_entry,
    render_report,
    resolve_input_file,
)
from aap_ee_inspector.models import ExecutionEnvironmentDetails


def make_details(**overrides) -> ExecutionEnvironmentDetails:
    defaults = {
        "names": ["some_ee:1.0"],
        "image": "registry.example.com/some_ee:1.0",
        "ansible_core_version": "2.16.17",
        "python_version": "3.12.12",
        "jinja_version": "3.1.6",
        "collections": {"community.vmware": "6.2.0", "amazon.aws": "9.5.1"},
    }
    defaults.update(overrides)
    return ExecutionEnvironmentDetails(**defaults)


class TestRenderEntry:
    def test_successful_entry_includes_versions_and_status(self):
        markdown = render_entry(make_details())
        assert "## some_ee:1.0" in markdown
        assert "- **Status**: OK" in markdown
        assert "ansible-core version**: `2.16.17`" in markdown
        assert "Python version**: `3.12.12`" in markdown
        assert "jinja version**: `3.1.6`" in markdown

    def test_collections_are_in_code_block_one_per_line_sorted(self):
        markdown = render_entry(make_details())
        lines = markdown.splitlines()
        start = lines.index("```")
        end = lines.index("```", start + 1)
        collection_lines = lines[start + 1 : end]
        assert collection_lines == ["amazon.aws 9.5.1", "community.vmware 6.2.0"]

    def test_no_collections_shows_placeholder(self):
        markdown = render_entry(make_details(collections={}))
        assert "_No collections found._" in markdown
        assert "```" not in markdown

    def test_multiple_names_joined_in_heading(self):
        markdown = render_entry(make_details(names=["EE-1", "EE-2"]))
        assert markdown.startswith("## EE-1 / EE-2")

    def test_no_pip_packages_section_when_empty(self):
        markdown = render_entry(make_details())
        assert "pip list" not in markdown

    def test_pip_packages_rendered_in_second_code_block_sorted(self):
        markdown = render_entry(
            make_details(python_packages={"cryptography": "50.0.1", "certifi": "2026.7.22"})
        )
        assert "Python packages installed (pip list)**: 2" in markdown
        lines = markdown.splitlines()
        blocks = [i for i, line in enumerate(lines) if line == "```"]
        assert len(blocks) == 4  # two code blocks: collections, then pip packages
        pip_start, pip_end = blocks[2], blocks[3]
        pip_lines = lines[pip_start + 1 : pip_end]
        assert pip_lines == ["certifi 2026.7.22", "cryptography 50.0.1"]

    def test_failed_entry_shows_error_and_skips_version_fields(self):
        markdown = render_entry(make_details(error="pull failed: unauthorized"))
        assert ":warning: FAILED - pull failed: unauthorized" in markdown
        assert "ansible-core version" not in markdown

    def test_failed_entry_collapses_multiline_error_to_one_line(self):
        markdown = render_entry(make_details(error="line one\nline two\nline three"))
        status_line = next(line for line in markdown.splitlines() if "FAILED" in line)
        assert "line one line two line three" in status_line


class TestRenderReport:
    def test_summary_counts_ok_and_failed(self):
        report = render_report([make_details(), make_details(error="boom")])
        assert "1 inspected successfully, 1 failed." in report

    def test_successful_entries_sorted_alphabetically_by_first_name(self):
        report = render_report(
            [
                make_details(names=["zebra_env:1.0"]),
                make_details(names=["alpha_env:1.0"]),
            ]
        )
        assert report.index("## alpha_env:1.0") < report.index("## zebra_env:1.0")

    def test_failed_entries_appear_in_trailing_section(self):
        report = render_report([make_details(), make_details(error="boom")])
        assert "# Failed / Skipped Images" in report
        assert report.index("# Failed / Skipped Images") > report.index("## some_ee:1.0")

    def test_no_failed_section_when_all_successful(self):
        report = render_report([make_details()])
        assert "# Failed / Skipped Images" not in report


class TestLoadDetails:
    def _write_details_file(self, tmp_path, entries, filename="details.json"):
        path = tmp_path / filename
        payload = [ExecutionEnvironmentDetails(**e).model_dump(mode="json") for e in entries]
        path.write_text(json.dumps(payload))
        return path

    def test_loads_all_entries_when_no_filter(self, tmp_path):
        path = self._write_details_file(
            tmp_path,
            [
                {"names": ["EE-1"], "image": "img-1"},
                {"names": ["EE-2"], "image": "img-2"},
            ],
        )
        assert len(load_details(path)) == 2

    def test_only_filters_by_name_pattern(self, tmp_path):
        path = self._write_details_file(
            tmp_path,
            [
                {"names": ["vmware_env:1.0"], "image": "img-1"},
                {"names": ["amfam_default:1.1"], "image": "img-2"},
            ],
        )
        result = load_details(path, only=["vmware_env:*"])
        assert len(result) == 1
        assert result[0].names == ["vmware_env:1.0"]

    def test_only_matches_if_any_name_matches(self, tmp_path):
        path = self._write_details_file(
            tmp_path,
            [{"names": ["EE-1", "EE-2"], "image": "img-1"}],
        )
        result = load_details(path, only=["EE-2"])
        assert len(result) == 1


class TestResolveInputFile:
    def test_raises_if_nothing_found_and_no_explicit_path(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path / "outputs"))
        with pytest.raises(FileNotFoundError):
            resolve_input_file(config, explicit_path=None)

    def test_raises_if_explicit_path_missing(self, tmp_path):
        config = AppConfig(output=OutputConfig(dir=tmp_path))
        with pytest.raises(FileNotFoundError):
            resolve_input_file(config, explicit_path=str(tmp_path / "nope.json"))

    def test_explicit_file_path_takes_precedence_over_latest(self, tmp_path):
        output_dir = tmp_path / "outputs"
        (output_dir / "20260101T000000").mkdir(parents=True)
        (output_dir / "20260101T000000" / "execution_environment_details.json").write_text("[]")
        explicit = tmp_path / "custom.json"
        explicit.write_text("[]")

        config = AppConfig(output=OutputConfig(dir=output_dir))
        result = resolve_input_file(config, explicit_path=str(explicit))
        assert result == explicit

    def test_explicit_run_dir_path_resolves_to_file_inside_it(self, tmp_path):
        output_dir = tmp_path / "outputs"
        run_dir = output_dir / "20260101T000000"
        run_dir.mkdir(parents=True)
        (run_dir / "execution_environment_details.json").write_text("[]")

        config = AppConfig(output=OutputConfig(dir=output_dir))
        result = resolve_input_file(config, explicit_path=str(run_dir))
        assert result == run_dir / "execution_environment_details.json"

    def test_picks_latest_when_no_explicit_path(self, tmp_path):
        output_dir = tmp_path / "outputs"
        (output_dir / "20260101T000000").mkdir(parents=True)
        (output_dir / "20260101T000000" / "execution_environment_details.json").write_text("[]")
        (output_dir / "20260601T000000").mkdir(parents=True)
        (output_dir / "20260601T000000" / "execution_environment_details.json").write_text("[]")

        config = AppConfig(output=OutputConfig(dir=output_dir))
        result = resolve_input_file(config, explicit_path=None)
        assert result.parent.name == "20260601T000000"
