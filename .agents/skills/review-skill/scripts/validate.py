#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate a skill directory against the Agent Skills specification.

Checks mechanical/structural rules that can be verified programmatically.
Qualitative checks (description quality, instruction clarity, etc.) are
handled by the LLM in the review-skill SKILL.md instructions.

Usage: python validate.py <path-to-skill-directory>
"""

import sys
import os
import re
import json

# ── helpers ──────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"

results = []


def record(category, check, status, detail=""):
    results.append({"category": category, "check": check, "status": status, "detail": detail})


def parse_frontmatter(text):
    """Extract YAML frontmatter from SKILL.md content. Returns (dict, body, error)."""
    if not text.startswith("---"):
        return None, text, "File does not start with '---' frontmatter delimiter"

    end = text.find("---", 3)
    if end == -1:
        return None, text, "No closing '---' frontmatter delimiter found"

    raw_fm = text[3:end].strip()
    body = text[end + 3:].strip()

    # Simple YAML-ish parser — handles the flat key: value pairs we care about.
    # For nested/multiline values we just capture the raw string.
    fm = {}
    current_key = None
    current_value_lines = []

    for line in raw_fm.split("\n"):
        # top-level key
        m = re.match(r"^([a-zA-Z_-]+)\s*:\s*(.*)", line)
        if m and not line.startswith("  ") and not line.startswith("\t"):
            if current_key is not None:
                fm[current_key] = "\n".join(current_value_lines).strip()
            current_key = m.group(1)
            current_value_lines = [m.group(2)]
        else:
            current_value_lines.append(line)

    if current_key is not None:
        fm[current_key] = "\n".join(current_value_lines).strip()

    # Clean up values — strip surrounding quotes, pipe-literal leading whitespace
    for k, v in fm.items():
        if v.startswith("|"):
            # YAML literal block — join continuation lines
            lines = v.split("\n")[1:]  # skip the '|' line
            fm[k] = "\n".join(l.strip() for l in lines).strip()
        elif v.startswith('"') and v.endswith('"'):
            fm[k] = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            fm[k] = v[1:-1]

    return fm, body, None


# ── checks ───────────────────────────────────────────────────────────

def check_file_structure(skill_dir):
    cat = "File structure"
    dir_name = os.path.basename(os.path.normpath(skill_dir))

    # Kebab-case folder name
    if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", dir_name):
        record(cat, "Folder name is kebab-case", PASS, dir_name)
    else:
        record(cat, "Folder name is kebab-case", FAIL, f"'{dir_name}' is not valid kebab-case (lowercase letters, numbers, hyphens only; no leading/trailing/consecutive hyphens)")

    # SKILL.md exists with exact casing
    entries = os.listdir(skill_dir)
    if "SKILL.md" in entries:
        record(cat, "SKILL.md exists with correct casing", PASS)
    else:
        # Check for case-insensitive variants
        variants = [e for e in entries if e.lower() == "skill.md"]
        if variants:
            record(cat, "SKILL.md exists with correct casing", FAIL, f"Found '{variants[0]}' — must be exactly 'SKILL.md'")
        else:
            record(cat, "SKILL.md exists with correct casing", FAIL, "No SKILL.md file found")
        return None, None, dir_name  # can't continue without SKILL.md

    # No README.md
    if "README.md" in entries or "readme.md" in entries:
        readme_variant = "README.md" if "README.md" in entries else "readme.md"
        record(cat, "No README.md in skill folder", FAIL, f"Found '{readme_variant}' — documentation should go in SKILL.md or references/")
    else:
        record(cat, "No README.md in skill folder", PASS)

    # Read SKILL.md
    skill_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()

    fm, body, err = parse_frontmatter(content)
    return fm, body, dir_name


def check_frontmatter(fm, body, dir_name):
    cat = "YAML frontmatter"

    if fm is None:
        record(cat, "Frontmatter present and parseable", FAIL, "Could not parse frontmatter")
        return

    record(cat, "Frontmatter present and parseable", PASS)

    # ── name field ──
    name = fm.get("name", "")
    if not name:
        record(cat, "name field present", FAIL, "Missing 'name' field")
    else:
        record(cat, "name field present", PASS, name)

        if len(name) <= 64:
            record(cat, "name ≤ 64 characters", PASS, f"{len(name)} chars")
        else:
            record(cat, "name ≤ 64 characters", FAIL, f"{len(name)} chars")

        if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
            record(cat, "name is valid kebab-case", PASS)
        else:
            issues = []
            if re.search(r"[A-Z]", name):
                issues.append("contains uppercase")
            if name.startswith("-") or name.endswith("-"):
                issues.append("starts or ends with hyphen")
            if "--" in name:
                issues.append("contains consecutive hyphens")
            if re.search(r"[^a-z0-9-]", name):
                issues.append("contains disallowed characters")
            record(cat, "name is valid kebab-case", FAIL, "; ".join(issues) if issues else "Invalid format")

        for reserved in ["anthropic", "claude"]:
            if reserved in name.lower():
                record(cat, f"name does not contain reserved word '{reserved}'", FAIL, f"'{name}' contains '{reserved}'")
            else:
                record(cat, f"name does not contain reserved word '{reserved}'", PASS)

        if name == dir_name:
            record(cat, "name matches directory name", PASS)
        else:
            record(cat, "name matches directory name", FAIL, f"name='{name}' but directory='{dir_name}'")

    # ── description field ──
    desc = fm.get("description", "")
    if not desc:
        record(cat, "description field present", FAIL, "Missing 'description' field")
    else:
        record(cat, "description field present", PASS)

        if len(desc) <= 1024:
            record(cat, "description ≤ 1,024 characters", PASS, f"{len(desc)} chars")
        else:
            record(cat, "description ≤ 1,024 characters", FAIL, f"{len(desc)} chars")

        if re.search(r"<[^>]*>", desc):
            record(cat, "description has no XML tags", FAIL, "Contains angle brackets that look like XML tags")
        else:
            record(cat, "description has no XML tags", PASS)

    # ── XML in entire frontmatter ──
    raw_fm_text = ""
    for k, v in fm.items():
        raw_fm_text += f"{k}: {v}\n"
    if re.search(r"<[^>]*>", raw_fm_text):
        record(cat, "No XML angle brackets in frontmatter", FAIL, "Found angle brackets in frontmatter values")
    else:
        record(cat, "No XML angle brackets in frontmatter", PASS)

    # ── optional field constraints ──
    if "compatibility" in fm and len(fm["compatibility"]) > 500:
        record(cat, "compatibility ≤ 500 characters", FAIL, f"{len(fm['compatibility'])} chars")
    elif "compatibility" in fm:
        record(cat, "compatibility ≤ 500 characters", PASS)

    # ── allowed-tools format ──
    if "allowed-tools" in fm:
        record(cat, "allowed-tools field present", PASS, str(fm["allowed-tools"])[:80])


def check_body(body, skill_dir):
    cat = "Skill body"

    if not body:
        record(cat, "Body is non-empty", FAIL, "SKILL.md has no body content after frontmatter")
        return

    record(cat, "Body is non-empty", PASS)

    lines = body.split("\n")
    line_count = len(lines)
    char_count = len(body)

    if line_count <= 500:
        record(cat, "Body ≤ 500 lines", PASS, f"{line_count} lines")
    else:
        record(cat, "Body ≤ 500 lines", WARN, f"{line_count} lines — consider moving content to references/")

    if char_count <= 20000:
        record(cat, "Body ≤ ~20,000 characters (~5k tokens)", PASS, f"{char_count} chars")
    else:
        record(cat, "Body ≤ ~20,000 characters (~5k tokens)", WARN, f"{char_count} chars — skill may consume excessive context")

    # Check if references/, scripts/, assets/ exist and are mentioned in body
    for subdir in ["references", "scripts", "assets"]:
        subdir_path = os.path.join(skill_dir, subdir)
        if os.path.isdir(subdir_path):
            files_in_subdir = [f for f in os.listdir(subdir_path) if not f.startswith(".")]
            if files_in_subdir:
                # Check that SKILL.md mentions this directory
                if subdir in body or any(f in body for f in files_in_subdir):
                    record(cat, f"Body references bundled {subdir}/ files", PASS)
                else:
                    record(cat, f"Body references bundled {subdir}/ files", WARN,
                           f"{subdir}/ exists with {len(files_in_subdir)} file(s) but is not mentioned in SKILL.md body")


def check_references(skill_dir, body):
    cat = "References"
    ref_dir = os.path.join(skill_dir, "references")

    if not os.path.isdir(ref_dir):
        record(cat, "references/ directory", SKIP, "No references/ directory")
        return

    ref_files = [f for f in os.listdir(ref_dir) if not f.startswith(".")]
    if not ref_files:
        record(cat, "references/ directory", SKIP, "references/ is empty")
        return

    for ref_file in ref_files:
        ref_path = os.path.join(ref_dir, ref_file)
        if not os.path.isfile(ref_path):
            continue

        # Check that the reference file is mentioned in the SKILL.md body
        if ref_file in (body or ""):
            record(cat, f"'{ref_file}' is linked from SKILL.md", PASS)
        else:
            record(cat, f"'{ref_file}' is linked from SKILL.md", WARN, "Reference file exists but is not mentioned in SKILL.md body")

        # Check for TOC if file is long
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                ref_content = f.read()
            ref_lines = ref_content.split("\n")
            if len(ref_lines) > 100:
                # Look for something resembling a TOC in the first 20 lines
                header = "\n".join(ref_lines[:20]).lower()
                has_toc = any(term in header for term in ["table of contents", "toc", "## contents", "# contents"])
                if has_toc:
                    record(cat, f"'{ref_file}' has TOC (>{len(ref_lines)} lines)", PASS)
                else:
                    record(cat, f"'{ref_file}' has TOC (>{len(ref_lines)} lines)", WARN,
                           f"File is {len(ref_lines)} lines but has no table of contents in the first 20 lines")
        except Exception:
            pass

    # Check for cross-references between reference files
    for ref_file in ref_files:
        ref_path = os.path.join(ref_dir, ref_file)
        if not os.path.isfile(ref_path):
            continue
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                ref_content = f.read()
            other_refs = [r for r in ref_files if r != ref_file]
            cross_refs = [r for r in other_refs if r in ref_content]
            if cross_refs:
                record(cat, f"'{ref_file}' has no cross-references", WARN,
                       f"References other file(s): {', '.join(cross_refs)} — keep references one level deep from SKILL.md")
            else:
                record(cat, f"'{ref_file}' has no cross-references", PASS)
        except Exception:
            pass


def check_scripts(skill_dir):
    cat = "Scripts"
    scripts_dir = os.path.join(skill_dir, "scripts")

    if not os.path.isdir(scripts_dir):
        record(cat, "scripts/ directory", SKIP, "No scripts/ directory")
        return

    script_files = [f for f in os.listdir(scripts_dir) if not f.startswith(".")]
    if not script_files:
        record(cat, "scripts/ directory", SKIP, "scripts/ is empty")
        return

    for script_file in script_files:
        script_path = os.path.join(scripts_dir, script_file)
        if not os.path.isfile(script_path):
            continue

        record(cat, f"Script found: '{script_file}'", PASS)

        # Check if script is executable (unix)
        if os.name != "nt":
            if os.access(script_path, os.X_OK):
                record(cat, f"'{script_file}' is executable", PASS)
            else:
                record(cat, f"'{script_file}' is executable", WARN, "File is not executable — consider chmod +x")


def check_security(fm, skill_dir):
    cat = "Security"

    # Walk all files for hardcoded secrets
    secret_patterns = [
        (r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9+/=_-]{20,}", "Possible API key"),
        (r"(?:secret|token|password|passwd)\s*[:=]\s*['\"][^\s'\"]{8,}", "Possible secret/token"),
        (r"sk-[A-Za-z0-9]{20,}", "Possible OpenAI/Anthropic secret key"),
        (r"ghp_[A-Za-z0-9]{36}", "Possible GitHub personal access token"),
        (r"xox[bpas]-[A-Za-z0-9-]{10,}", "Possible Slack token"),
    ]

    found_secrets = False
    for root, dirs, files in os.walk(skill_dir):
        # skip hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.startswith("."):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for pattern, label in secret_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        rel_path = os.path.relpath(fpath, skill_dir)
                        record(cat, f"No hardcoded secrets in '{rel_path}'", FAIL, label)
                        found_secrets = True
            except Exception:
                pass

    if not found_secrets:
        record(cat, "No hardcoded secrets detected", PASS)

    # Check for backslash paths
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.startswith(".") or not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Look for Windows-style paths like references\file.md or scripts\run.py
                if re.search(r"(?:references|scripts|assets)\\", content):
                    rel_path = os.path.relpath(fpath, skill_dir)
                    record(cat, f"No backslash paths in '{rel_path}'", FAIL, "Use forward slashes in file paths")
            except Exception:
                pass


# ── main ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python validate.py <path-to-skill-directory>")
        print("       python validate.py <path-to-SKILL.md>")
        sys.exit(2)

    target = sys.argv[1]

    # Accept either a directory or a SKILL.md file path
    if os.path.isfile(target) and os.path.basename(target) == "SKILL.md":
        skill_dir = os.path.dirname(target)
    elif os.path.isdir(target):
        skill_dir = target
    else:
        print(f"Error: '{target}' is not a valid skill directory or SKILL.md file")
        sys.exit(2)

    skill_dir = os.path.abspath(skill_dir)

    # Announce
    print(f"Validating skill: {skill_dir}")
    print(f"{'=' * 60}")

    # Run checks
    fm, body, dir_name = check_file_structure(skill_dir)
    if fm is not None:
        check_frontmatter(fm, body, dir_name)
        check_body(body, skill_dir)
        check_references(skill_dir, body)
        check_scripts(skill_dir)
        check_security(fm, skill_dir)
    elif dir_name is not None:
        # SKILL.md not found — still check security on the directory
        check_security({}, skill_dir)

    # ── report ───────────────────────────────────────────────────────
    print()

    fails = [r for r in results if r["status"] == FAIL]
    warns = [r for r in results if r["status"] == WARN]
    passes = [r for r in results if r["status"] == PASS]
    skips = [r for r in results if r["status"] == SKIP]

    current_category = None
    for r in results:
        if r["category"] != current_category:
            current_category = r["category"]
            print(f"\n── {current_category} ──")

        icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "–"}[r["status"]]
        line = f"  {icon} {r['check']}"
        if r["detail"]:
            line += f"  ({r['detail']})"
        print(line)

    # ── summary ──────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Results: {len(passes)} passed, {len(fails)} failed, {len(warns)} warnings, {len(skips)} skipped")

    if fails:
        print(f"\nFAILURES:")
        for r in fails:
            detail = f" — {r['detail']}" if r['detail'] else ""
            print(f"  ✗ [{r['category']}] {r['check']}{detail}")

    if warns:
        print(f"\nWARNINGS:")
        for r in warns:
            detail = f" — {r['detail']}" if r['detail'] else ""
            print(f"  ⚠ [{r['category']}] {r['check']}{detail}")

    # ── JSON output for programmatic use ─────────────────────────────
    json_path = os.path.join(skill_dir, ".validation-result.json")
    summary = {
        "skill_dir": skill_dir,
        "pass_count": len(passes),
        "fail_count": len(fails),
        "warn_count": len(warns),
        "skip_count": len(skips),
        "results": results,
    }
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nDetailed results written to: {json_path}")

    # Exit code: 1 if any failures, 0 otherwise
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
