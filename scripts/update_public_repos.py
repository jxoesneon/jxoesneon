import argparse
import datetime
import json
import os
import subprocess
import sys
from typing import Any


START_MARKER = "<!-- BEGIN PUBLIC_REPOS -->"
END_MARKER = "<!-- END PUBLIC_REPOS -->"

LATEST_RELEASES_START = "<!-- BEGIN LATEST_RELEASES -->"
LATEST_RELEASES_END = "<!-- END LATEST_RELEASES -->"

MCP_ECOSYSTEM_START = "<!-- BEGIN MCP_ECOSYSTEM -->"
MCP_ECOSYSTEM_END = "<!-- END MCP_ECOSYSTEM -->"

CORE_LIBRARIES_START = "<!-- BEGIN CORE_LIBRARIES -->"
CORE_LIBRARIES_END = "<!-- END CORE_LIBRARIES -->"


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def _run_optional(cmd: list[str]) -> str | None:
    try:
        return _run(cmd)
    except subprocess.CalledProcessError:
        return None


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def fetch_public_repos(owner: str) -> list[dict[str, Any]]:
    raw = _run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"users/{owner}/repos?per_page=100&sort=updated&direction=desc",
        ]
    )
    pages: list[Any] = json.loads(raw)

    flattened: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            for repo in page:
                if isinstance(repo, dict):
                    flattened.append(repo)

    repos: list[dict[str, Any]] = []
    for repo in flattened:
        if repo.get("private") is True:
            continue

        repos.append(
            {
                "name": repo.get("name"),
                "description": repo.get("description"),
                "primaryLanguage": {"name": repo.get("language")},
                "stargazersCount": repo.get("stargazers_count"),
                "fork": repo.get("fork"),
                "isArchived": repo.get("archived"),
                "updatedAt": repo.get("updated_at"),
                "url": repo.get("html_url"),
            }
        )

    def sort_key(r: dict[str, Any]) -> str:
        return r.get("updatedAt") or ""

    repos.sort(key=sort_key, reverse=True)
    return repos


def _iso_date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value


def fetch_latest_release(owner: str, repo_name: str) -> dict[str, Any] | None:
    raw = _run_optional(["gh", "api", f"repos/{owner}/{repo_name}/releases/latest"])
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def render_latest_releases(owner: str, repos: list[dict[str, Any]], limit: int = 6) -> str:
    limit = 4 if limit <= 0 else limit
    releases: list[dict[str, Any]] = []
    for r in repos:
        if r.get("fork") is True:
            continue
        if r.get("isArchived") is True:
            continue
        name = r.get("name") or ""
        if not name:
            continue

        rel = fetch_latest_release(owner, name)
        if not rel:
            continue

        tag = rel.get("tag_name") or ""
        published = rel.get("published_at") or ""

        releases.append(
            {
                "repo": r,
                "tag": tag,
                "published_at": published,
                "release_name": rel.get("name") or "",
            }
        )

    releases.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    releases = releases[:limit]

    lines: list[str] = []
    lines.append("| Project | Version | Description |")
    lines.append("| :------ | :------ | :---------- |")

    for item in releases:
        repo = item["repo"]
        repo_name = repo.get("name") or ""
        url = repo.get("url") or ""
        tag = item.get("tag") or ""
        desc = item.get("release_name") or repo.get("description") or ""
        desc = _escape_md(desc)

        project = f"**[{_escape_md(repo_name)}]({url})**" if url else f"**{_escape_md(repo_name)}**"
        version = f"`{_escape_md(tag)}`" if tag else ""
        lines.append(f"| {project} | {version} | {desc} |")

    return "\n".join(lines).rstrip() + "\n"


def render_mcp_ecosystem(repos: list[dict[str, Any]]) -> str:
    def is_mcp(repo: dict[str, Any]) -> bool:
        name = (repo.get("name") or "").lower()
        desc = (repo.get("description") or "").lower()
        if "mcp" in name:
            return True
        if "model context protocol" in desc:
            return True
        if "mcp server" in desc:
            return True
        return False

    matches = [r for r in repos if is_mcp(r)]
    matches.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)
    matches.sort(key=lambda r: (r.get("stargazersCount") or 0), reverse=True)
    matches.sort(key=lambda r: (r.get("fork") is True))

    lines: list[str] = []
    for r in matches:
        name = r.get("name") or ""
        url = r.get("url") or ""
        desc = _escape_md(r.get("description") or "")
        if not name:
            continue

        label = f"**[{_escape_md(name)}]({url})**" if url else f"**{_escape_md(name)}**"
        if desc:
            lines.append(f"- {label}: {desc}")
        else:
            lines.append(f"- {label}")

    return "\n".join(lines).rstrip() + "\n"


def render_core_libraries(repos: list[dict[str, Any]], limit: int = 3) -> str:
    def is_candidate(repo: dict[str, Any]) -> bool:
        name = (repo.get("name") or "").lower()
        if repo.get("fork") is True:
            return False
        if repo.get("isArchived") is True:
            return False
        if name in {".github", "jxoesneon.github.io"}:
            return False
        if name == "jxoesneon":
            return False
        return True

    candidates = [r for r in repos if is_candidate(r)]
    candidates.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)
    candidates.sort(key=lambda r: (r.get("stargazersCount") or 0), reverse=True)
    candidates = candidates[:limit]

    lines: list[str] = []
    for r in candidates:
        name = r.get("name") or ""
        url = r.get("url") or ""
        desc = (r.get("description") or "").strip()

        primary = r.get("primaryLanguage") or {}
        lang = primary.get("name") if isinstance(primary, dict) else ""
        lang = (lang or "").strip()

        stars = r.get("stargazersCount")
        stars = str(stars) if isinstance(stars, int) else "0"

        if not name:
            continue

        title = f"### [{_escape_md(name)}]({url})" if url else f"### {_escape_md(name)}"
        lines.append(title)
        lines.append("")
        if desc:
            lines.append(f"> {_escape_md(desc)}")
        meta_bits: list[str] = []
        if lang:
            meta_bits.append(lang)
        meta_bits.append(f"{stars}★")
        if meta_bits:
            lines.append(f"> _{' • '.join(meta_bits)}_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_table(repos: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    lines.append(f"Public repositories: **{len(repos)}**")
    lines.append("")
    lines.append("| Repo | Description | Lang | Stars | Updated |")
    lines.append("| :--- | :---------- | :--- | ----: | :------ |")

    for r in repos:
        name = r.get("name") or ""
        url = r.get("url") or ""
        desc = _escape_md(r.get("description") or "")

        primary = r.get("primaryLanguage") or {}
        lang = primary.get("name") if isinstance(primary, dict) else ""
        lang = _escape_md(lang or "")

        stars = r.get("stargazersCount")
        stars = str(stars) if isinstance(stars, int) else "0"

        updated = _iso_date(r.get("updatedAt") or "")

        flags: list[str] = []
        if r.get("fork") is True:
            flags.append("fork")
        if r.get("isArchived") is True:
            flags.append("archived")
        flag_suffix = f" ({', '.join(flags)})" if flags else ""

        repo_cell = f"[{_escape_md(name)}]({url}){flag_suffix}" if url else _escape_md(name)
        lines.append(f"| {repo_cell} | {desc} | {lang} | {stars} | {updated} |")

    return "\n".join(lines).rstrip() + "\n"


def replace_block(readme_text: str, start_marker: str, end_marker: str, new_block: str) -> str:
    start_idx = readme_text.find(start_marker)
    if start_idx == -1:
        raise ValueError(f"Start marker not found: {start_marker}")

    end_idx = readme_text.find(end_marker)
    if end_idx == -1:
        raise ValueError(f"End marker not found: {end_marker}")

    if end_idx < start_idx:
        raise ValueError("End marker appears before start marker")

    start_content_idx = start_idx + len(start_marker)
    return (
        readme_text[:start_content_idx]
        + "\n\n"
        + new_block.rstrip()
        + "\n\n"
        + readme_text[end_idx:]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    parser.add_argument("--readme", default="README.md")
    args = parser.parse_args()

    owner = args.owner
    if not owner:
        owner = _run(["gh", "api", "user", "--jq", ".login"]).strip()

    repos = fetch_public_repos(owner)
    rendered_public_repos = render_table(repos)
    rendered_latest_releases = render_latest_releases(owner, repos)
    rendered_mcp_ecosystem = render_mcp_ecosystem(repos)
    rendered_core_libraries = render_core_libraries(repos)

    with open(args.readme, "r", encoding="utf-8") as f:
        readme = f.read()

    updated = readme
    updated = replace_block(updated, LATEST_RELEASES_START, LATEST_RELEASES_END, rendered_latest_releases)
    updated = replace_block(updated, MCP_ECOSYSTEM_START, MCP_ECOSYSTEM_END, rendered_mcp_ecosystem)
    updated = replace_block(updated, CORE_LIBRARIES_START, CORE_LIBRARIES_END, rendered_core_libraries)
    updated = replace_block(updated, START_MARKER, END_MARKER, rendered_public_repos)

    if updated != readme:
        with open(args.readme, "w", encoding="utf-8") as f:
            f.write(updated)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr or "")
        sys.stderr.write("\n")
        return_code = e.returncode if isinstance(e.returncode, int) else 1
        raise SystemExit(return_code)
