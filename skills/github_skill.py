# -*- coding: utf-8 -*-
"""
ArcMind Skill: GitHub Integration
===================================
完整 GitHub REST API 整合。

Actions:
  list_repos, get_repo_status, create_pr, list_prs, merge_pr,
  list_issues, create_issue, close_issue, comment,
  list_actions, trigger_action, create_release
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("arcmind.skills.github")


def _get_token() -> str:
    from config.settings import settings
    token = getattr(settings, "github_token", "")
    if not token:
        raise ValueError("GITHUB_TOKEN not configured in .env")
    return token


def _get_default_owner() -> str:
    from config.settings import settings
    return getattr(settings, "github_default_owner", "")


def _api(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    """Call GitHub REST API."""
    base = "https://api.github.com"
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ArcMind/0.3",
    }

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {e.code}: {error_body[:300]}") from e


# ── Actions ──────────────────────────────────────────────────────────────────

def _list_repos(inputs: dict, token: str) -> dict:
    """List user's repositories."""
    owner = inputs.get("owner", _get_default_owner())
    repos = _api("GET", f"/users/{owner}/repos", token, params={
        "sort": "updated", "per_page": str(inputs.get("limit", 20)),
    })
    return {
        "repos": [
            {
                "name": r["full_name"],
                "description": r.get("description", ""),
                "stars": r.get("stargazers_count", 0),
                "language": r.get("language", ""),
                "updated": r.get("updated_at", ""),
                "private": r.get("private", False),
            }
            for r in repos
        ],
        "count": len(repos),
    }


def _get_repo_status(inputs: dict, token: str) -> dict:
    """Get repository overview."""
    repo = inputs["repo"]  # "owner/repo"
    info = _api("GET", f"/repos/{repo}", token)
    commits = _api("GET", f"/repos/{repo}/commits", token, params={"per_page": "5"})
    return {
        "name": info["full_name"],
        "description": info.get("description", ""),
        "stars": info.get("stargazers_count", 0),
        "forks": info.get("forks_count", 0),
        "open_issues": info.get("open_issues_count", 0),
        "default_branch": info.get("default_branch", "main"),
        "language": info.get("language", ""),
        "recent_commits": [
            {"sha": c["sha"][:7], "message": c["commit"]["message"][:80],
             "author": c["commit"]["author"]["name"],
             "date": c["commit"]["author"]["date"]}
            for c in commits[:5]
        ],
    }


def _create_pr(inputs: dict, token: str) -> dict:
    """Create a pull request."""
    repo = inputs["repo"]
    body = {
        "title": inputs["title"],
        "head": inputs["head"],
        "base": inputs.get("base", "main"),
        "body": inputs.get("body", ""),
    }
    pr = _api("POST", f"/repos/{repo}/pulls", token, body=body)
    return {"pr_number": pr["number"], "url": pr["html_url"], "state": pr["state"]}


def _list_prs(inputs: dict, token: str) -> dict:
    """List pull requests."""
    repo = inputs["repo"]
    state = inputs.get("state", "open")
    prs = _api("GET", f"/repos/{repo}/pulls", token, params={
        "state": state, "per_page": str(inputs.get("limit", 10)),
    })
    return {
        "prs": [
            {"number": p["number"], "title": p["title"], "state": p["state"],
             "author": p["user"]["login"], "url": p["html_url"],
             "created": p["created_at"]}
            for p in prs
        ],
    }


def _merge_pr(inputs: dict, token: str) -> dict:
    """Merge a pull request."""
    repo = inputs["repo"]
    pr_number = inputs["pr_number"]
    method = inputs.get("merge_method", "squash")  # merge/squash/rebase
    result = _api("PUT", f"/repos/{repo}/pulls/{pr_number}/merge", token, body={
        "merge_method": method,
    })
    return {"merged": result.get("merged", False), "message": result.get("message", "")}


def _list_issues(inputs: dict, token: str) -> dict:
    """List issues."""
    repo = inputs["repo"]
    state = inputs.get("state", "open")
    issues = _api("GET", f"/repos/{repo}/issues", token, params={
        "state": state, "per_page": str(inputs.get("limit", 10)),
    })
    # Filter out PRs (GitHub API returns PRs as issues too)
    issues = [i for i in issues if "pull_request" not in i]
    return {
        "issues": [
            {"number": i["number"], "title": i["title"], "state": i["state"],
             "author": i["user"]["login"], "labels": [l["name"] for l in i.get("labels", [])],
             "created": i["created_at"]}
            for i in issues
        ],
    }


def _create_issue(inputs: dict, token: str) -> dict:
    """Create an issue."""
    repo = inputs["repo"]
    body = {
        "title": inputs["title"],
        "body": inputs.get("body", ""),
    }
    if inputs.get("labels"):
        body["labels"] = inputs["labels"]
    if inputs.get("assignees"):
        body["assignees"] = inputs["assignees"]
    issue = _api("POST", f"/repos/{repo}/issues", token, body=body)
    return {"number": issue["number"], "url": issue["html_url"]}


def _close_issue(inputs: dict, token: str) -> dict:
    """Close an issue."""
    repo = inputs["repo"]
    issue_number = inputs["issue_number"]
    result = _api("PATCH", f"/repos/{repo}/issues/{issue_number}", token, body={
        "state": "closed",
    })
    return {"number": result["number"], "state": result["state"]}


def _comment(inputs: dict, token: str) -> dict:
    """Comment on an issue or PR."""
    repo = inputs["repo"]
    number = inputs["number"]
    body = inputs["body"]
    result = _api("POST", f"/repos/{repo}/issues/{number}/comments", token, body={
        "body": body,
    })
    return {"id": result["id"], "url": result["html_url"]}


def _list_actions(inputs: dict, token: str) -> dict:
    """List recent workflow runs."""
    repo = inputs["repo"]
    runs = _api("GET", f"/repos/{repo}/actions/runs", token, params={
        "per_page": str(inputs.get("limit", 10)),
    })
    return {
        "runs": [
            {"id": r["id"], "name": r["name"], "status": r["status"],
             "conclusion": r.get("conclusion", ""),
             "branch": r["head_branch"], "created": r["created_at"],
             "url": r["html_url"]}
            for r in runs.get("workflow_runs", [])
        ],
    }


def _trigger_action(inputs: dict, token: str) -> dict:
    """Trigger a workflow dispatch."""
    repo = inputs["repo"]
    workflow_id = inputs["workflow_id"]  # filename or ID
    ref = inputs.get("ref", "main")
    _api("POST", f"/repos/{repo}/actions/workflows/{workflow_id}/dispatches", token, body={
        "ref": ref,
        "inputs": inputs.get("workflow_inputs", {}),
    })
    return {"triggered": True, "workflow": workflow_id, "ref": ref}


def _create_release(inputs: dict, token: str) -> dict:
    """Create a release."""
    repo = inputs["repo"]
    body = {
        "tag_name": inputs["tag"],
        "name": inputs.get("name", inputs["tag"]),
        "body": inputs.get("body", ""),
        "draft": inputs.get("draft", False),
        "prerelease": inputs.get("prerelease", False),
    }
    release = _api("POST", f"/repos/{repo}/releases", token, body=body)
    return {"id": release["id"], "url": release["html_url"], "tag": release["tag_name"]}


# ── Main Entry Point ─────────────────────────────────────────────────────────

_ACTIONS = {
    "list_repos": _list_repos,
    "get_repo_status": _get_repo_status,
    "create_pr": _create_pr,
    "list_prs": _list_prs,
    "merge_pr": _merge_pr,
    "list_issues": _list_issues,
    "create_issue": _create_issue,
    "close_issue": _close_issue,
    "comment": _comment,
    "list_actions": _list_actions,
    "trigger_action": _trigger_action,
    "create_release": _create_release,
}


def run(inputs: dict) -> dict:
    """
    GitHub skill entry point.

    inputs:
      action: one of the action names above
      + action-specific params (repo, title, etc.)
    """
    action = inputs.get("action", "")
    if action not in _ACTIONS:
        return {
            "error": f"Unknown action: {action}",
            "available": list(_ACTIONS.keys()),
        }

    try:
        token = _get_token()
        result = _ACTIONS[action](inputs, token)
        return {"status": "ok", **result}
    except Exception as e:
        logger.error("[GitHub] %s failed: %s", action, e)
        return {"status": "error", "error": str(e)}
