from scripts.init_template import (
    filter_html_markers,
    filter_yaml_markers,
    strip_interview,
    strip_stack_job_prefix,
    fill_placeholders,
)


def test_filter_html_keeps_chosen_unwraps_markers() -> None:
    text = (
        "A\n<!-- STACK:python -->\nPY\n<!-- /STACK:python -->\n"
        "<!-- STACK:react -->\nRE\n<!-- /STACK:react -->\nB\n"
    )
    out = filter_html_markers(text, "python")
    assert "PY" in out
    assert "RE" not in out
    assert "STACK:python" not in out
    assert "STACK:react" not in out


def test_filter_html_react_drops_python() -> None:
    text = "<!-- STACK:python -->\nPY\n<!-- /STACK:python -->\n<!-- STACK:react -->\nRE\n<!-- /STACK:react -->\n"
    out = filter_html_markers(text, "react")
    assert "RE" in out and "PY" not in out


def test_filter_yaml_keeps_chosen() -> None:
    text = (
        "jobs:\n# >>> STACK:python\n  py: 1\n# <<< STACK:python\n"
        "# >>> STACK:react\n  re: 2\n# <<< STACK:react\n"
        "# >>> STACK:template\n  tmpl: 3\n# <<< STACK:template\n"
    )
    out = filter_yaml_markers(text, "python")
    assert "py: 1" in out
    assert "re: 2" not in out
    assert "tmpl: 3" not in out  # the template job is dropped post-init
    assert "STACK:" not in out


def test_strip_stack_job_prefix_renames_only_job_id_lines() -> None:
    text = (
        "jobs:\n"
        "  react-lint:\n"
        "    steps:\n"
        "      - run: echo react-lint step\n"
        "  react-tests:\n"
        "  react-security:\n"
    )
    out = strip_stack_job_prefix(text, "react")
    assert "  lint:\n" in out
    assert "  tests:\n" in out
    assert "  security:\n" in out
    assert "  react-lint:" not in out
    # non-job-id occurrences of the prefix are untouched
    assert "echo react-lint step" in out


def test_strip_stack_job_prefix_leaves_other_stack_alone() -> None:
    text = "  python-lint:\n  react-lint:\n"
    out = strip_stack_job_prefix(text, "react")
    assert "  python-lint:\n" in out
    assert "  lint:\n" in out


def test_strip_interview_removes_block() -> None:
    text = "intro\n<!-- INTERVIEW:start -->\nPROMPT\n<!-- INTERVIEW:end -->\noutro\n"
    out = strip_interview(text)
    assert "PROMPT" not in out
    assert "intro" in out and "outro" in out


def test_fill_placeholders() -> None:
    text = "name={{PROJECT_NAME}} desc={{DESCRIPTION}}"
    assert fill_placeholders(text, "acme", "a thing") == "name=acme desc=a thing"
