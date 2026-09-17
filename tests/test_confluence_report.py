"""Unit tests for aap_ee_inspector.confluence_report."""

from aap_ee_inspector.confluence_report import (
    render_entry_storage,
    render_exclusions_footnote_storage,
    render_report_storage,
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


class TestRenderEntryStorage:
    def test_successful_entry_includes_versions_and_status(self):
        html = render_entry_storage(make_details())
        assert "<h2>some_ee:1.0</h2>" in html
        assert "<li><strong>Status</strong>: OK</li>" in html
        assert "<strong>ansible-core version</strong>: <code>2.16.17</code>" in html
        assert "<strong>Python version</strong>: <code>3.12.12</code>" in html
        assert "<strong>jinja version</strong>: <code>3.1.6</code>" in html

    def test_collections_rendered_as_code_macro_sorted(self):
        html = render_entry_storage(make_details())
        assert '<ac:structured-macro ac:name="code">' in html
        assert '<ac:parameter ac:name="language">none</ac:parameter>' in html
        assert "<ac:plain-text-body><![CDATA[amazon.aws 9.5.1\ncommunity.vmware 6.2.0]]>" in html

    def test_no_collections_shows_placeholder(self):
        html = render_entry_storage(make_details(collections={}))
        assert "<em>No collections found.</em>" in html
        assert "ac:structured-macro" not in html

    def test_multiple_names_joined_in_heading(self):
        html = render_entry_storage(make_details(names=["EE-1", "EE-2"]))
        assert html.startswith("<h2>EE-1 / EE-2</h2>")

    def test_pip_packages_rendered_in_second_code_macro(self):
        html = render_entry_storage(
            make_details(python_packages={"cryptography": "50.0.1", "certifi": "2026.7.22"})
        )
        assert "Python packages installed (pip list)" in html
        assert html.count('<ac:structured-macro ac:name="code">') == 2
        assert "certifi 2026.7.22\ncryptography 50.0.1" in html

    def test_no_pip_packages_section_when_empty(self):
        html = render_entry_storage(make_details())
        assert "pip list" not in html

    def test_failed_entry_shows_error_and_skips_version_fields(self):
        html = render_entry_storage(make_details(error="pull failed: unauthorized"))
        assert "FAILED - pull failed: unauthorized" in html
        assert "ansible-core version" not in html

    def test_failed_entry_collapses_multiline_error(self):
        html = render_entry_storage(make_details(error="line one\nline two\nline three"))
        assert "line one line two line three" in html
        assert "\n" not in html.split("FAILED - ")[1].split("</li>")[0]

    def test_html_special_characters_are_escaped(self):
        html = render_entry_storage(make_details(names=["EE <special> & 'chars'"]))
        assert "<special>" not in html
        assert "&lt;special&gt;" in html
        assert "&amp;" in html


class TestRenderReportStorage:
    def test_summary_counts_ok_and_failed(self):
        html = render_report_storage([make_details(), make_details(error="boom")])
        assert "1 inspected successfully, 1 failed." in html

    def test_successful_entries_sorted_alphabetically_by_first_name(self):
        html = render_report_storage(
            [
                make_details(names=["zebra_env:1.0"]),
                make_details(names=["alpha_env:1.0"]),
            ]
        )
        assert html.index("<h2>alpha_env:1.0</h2>") < html.index("<h2>zebra_env:1.0</h2>")

    def test_failed_entries_appear_in_trailing_section(self):
        html = render_report_storage([make_details(), make_details(error="boom")])
        assert "<h1>Failed / Skipped Images</h1>" in html
        assert html.index("<h1>Failed / Skipped Images</h1>") > html.index("<h2>some_ee:1.0</h2>")

    def test_no_failed_section_when_all_successful(self):
        html = render_report_storage([make_details()])
        assert "Failed / Skipped Images" not in html


class TestRenderExclusionsFootnoteStorage:
    def test_empty_list_returns_empty_string(self):
        assert render_exclusions_footnote_storage([]) == ""

    def test_renders_patterns_as_list_items(self):
        html = render_exclusions_footnote_storage(["rhel6_env:*", "Minimal execution environment"])
        assert "<h2>Excluded Execution Environments</h2>" in html
        assert "<li><code>rhel6_env:*</code></li>" in html
        assert "<li><code>Minimal execution environment</code></li>" in html

    def test_escapes_special_characters_in_patterns(self):
        html = render_exclusions_footnote_storage(["<script>alert(1)</script>"])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
