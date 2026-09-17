"""Render execution environment details into Confluence storage-format XHTML.

Mirrors generate_report.py's Markdown renderer, but emits Confluence's
native storage format directly (rather than converting Markdown), so
collection listings render as proper Confluence code-block macros.
"""

from __future__ import annotations

from html import escape

from aap_ee_inspector.models import ExecutionEnvironmentDetails


def _code_macro(lines: list[str]) -> str:
    """Render `lines` as a Confluence code-block macro (language: none).

    Uses a CDATA section so the plain-text body doesn't need HTML-escaping
    for characters like `<`/`&` that can legitimately appear in collection
    or package names/versions.
    """
    body = "\n".join(lines)
    # A literal "]]>" inside CDATA would terminate it early; split any such
    # sequence across two CDATA sections as the standard XML workaround.
    body = body.replace("]]>", "]]]]><![CDATA[>")
    return (
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">none</ac:parameter>'
        f"<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def _bullet(label: str, value: str) -> str:
    """Render a `<li><strong>label</strong>: <code>value</code></li>` bullet."""
    return f"<li><strong>{label}</strong>: <code>{escape(value)}</code></li>"


def render_entry_storage(details: ExecutionEnvironmentDetails) -> str:
    """Render a single image's details as a Confluence storage-format section."""
    heading = escape(" / ".join(details.names))
    parts = [
        f"<h2>{heading}</h2>",
        "<ul>",
        _bullet("Image", details.image),
    ]

    if details.error:
        # Collapse multi-line subprocess error output to keep the bullet on one line.
        error_text = escape(details.error.replace("\n", " ").strip())
        parts.append(f"<li><strong>Status</strong>: \u26a0\ufe0f FAILED - {error_text}</li>")
        parts.append("</ul>")
        return "".join(parts)

    parts.append("<li><strong>Status</strong>: OK</li>")
    parts.append(_bullet("ansible-core version", details.ansible_core_version or "unknown"))
    parts.append(_bullet("Python version", details.python_version or "unknown"))
    parts.append(_bullet("jinja version", details.jinja_version or "unknown"))
    parts.append(f"<li><strong>Collections installed</strong>: {len(details.collections)}</li>")
    parts.append("</ul>")

    if details.collections:
        collection_lines = [
            f"{name} {details.collections[name]}" for name in sorted(details.collections)
        ]
        parts.append(_code_macro(collection_lines))
    else:
        parts.append("<p><em>No collections found.</em></p>")

    if details.python_packages:
        count = len(details.python_packages)
        parts.append(f"<p><strong>Python packages installed (pip list)</strong>: {count}</p>")
        package_lines = [
            f"{name} {details.python_packages[name]}" for name in sorted(details.python_packages)
        ]
        parts.append(_code_macro(package_lines))

    return "".join(parts)


def render_report_storage(all_details: list[ExecutionEnvironmentDetails]) -> str:
    """Render the full report as Confluence storage-format XHTML."""
    ok = [d for d in all_details if not d.error]
    failed = [d for d in all_details if d.error]

    summary = (
        f"Generated from {len(all_details)} unique execution environment image(s): "
        f"{len(ok)} inspected successfully, {len(failed)} failed."
    )
    parts = ["<h1>Execution Environment Report</h1>", f"<p>{escape(summary)}</p>", "<hr/>"]

    parts.extend(render_entry_storage(d) for d in sorted(ok, key=lambda d: d.names[0].lower()))

    if failed:
        parts.append("<hr/>")
        parts.append("<h1>Failed / Skipped Images</h1>")
        parts.extend(
            render_entry_storage(d) for d in sorted(failed, key=lambda d: d.names[0].lower())
        )

    return "".join(parts)


def render_exclusions_footnote_storage(name_patterns: list[str]) -> str:
    """Render the excluded-EE footnote as Confluence storage-format XHTML.

    Returns an empty string if `name_patterns` is empty (no footnote needed).
    """
    if not name_patterns:
        return ""

    items = "".join(f"<li><code>{escape(pattern)}</code></li>" for pattern in name_patterns)
    return (
        "<hr/>"
        "<h2>Excluded Execution Environments</h2>"
        "<p>The following EE name patterns are excluded from inspection "
        "(see <code>[exclusions].name_patterns</code> in <code>config.toml</code>) "
        "and will never appear above:</p>"
        f"<ul>{items}</ul>"
    )
