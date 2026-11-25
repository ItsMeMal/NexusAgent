"""
nexus/github_app/commands.py
CLI + gateway slash-command handler for GitHub App integration.

Commands (all prefixed with /github in gateway; bare subcommands in CLI):
  /github status            — show App info + installation token status
  /github repos             — list accessible repositories
  /github issues <owner/repo> [open|closed|all]
  /github prs <owner/repo>  [open|closed|all]
  /github view issue <owner/repo> <number>
  /github view pr <owner/repo> <number>
  /github diff <owner/repo> <pr_number>
  /github comment <owner/repo> <number> <text>
  /github review <owner/repo> <pr_number> <APPROVE|REQUEST_CHANGES|COMMENT> <body>
  /github setup             — interactive wizard to configure App creds in .env
"""

from __future__ import annotations

import os
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy auth singleton  (don't import at module level — deps may not be ready)
# ---------------------------------------------------------------------------

_auth_instance = None


def _get_auth():
    """Return a cached GitHubAppAuth instance, or None if not configured."""
    global _auth_instance
    if _auth_instance is not None:
        return _auth_instance
    try:
        from nexus.github_app.auth import GitHubAppAuth
        if GitHubAppAuth.available():
            _auth_instance = GitHubAppAuth.from_env()
    except Exception as exc:
        logger.debug("GitHub App auth not available: %s", exc)
    return _auth_instance


def _get_client():
    """Return a GitHubAppClient backed by the cached auth, or None."""
    auth = _get_auth()
    if auth is None:
        return None
    from nexus.github_app.client import GitHubAppClient
    return GitHubAppClient(auth)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_repo(r: dict) -> str:
    stars = r.get("stargazers_count", 0)
    vis = r.get("visibility", "?")
    lang = r.get("language") or "?"
    return f"  📦 {r['full_name']} [{vis}] ⭐{stars} {lang}"


def _fmt_issue(i: dict) -> str:
    state_icon = "🟢" if i.get("state") == "open" else "🔴"
    is_pr = "pull_request" in i
    kind = "PR" if is_pr else "Issue"
    return (
        f"  {state_icon} #{i['number']} [{kind}] {i['title']}\n"
        f"       by {i['user']['login']} · {i.get('comments', 0)} comments"
    )


def _fmt_pr(p: dict) -> str:
    state_icon = "🟢" if p.get("state") == "open" else "🔴"
    merged = "✅ Merged" if p.get("merged_at") else ""
    return (
        f"  {state_icon} #{p['number']} {p['title']} {merged}\n"
        f"       {p['head']['label']} → {p['base']['label']} · by {p['user']['login']}"
    )


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

async def handle_github_command(args: list[str], send: callable) -> None:
    """
    Dispatch a /github subcommand.
    `args`   — list of whitespace-split tokens after "/github" (may be empty)
    `send`   — async callable(text: str) to send a response message
    """
    if not args:
        await send(HELP_TEXT)
        return

    sub = args[0].lower()

    # ---- setup wizard -------------------------------------------------------
    if sub == "setup":
        await _cmd_setup(send)
        return

    # ---- check configured ---------------------------------------------------
    client = _get_client()
    if client is None:
        await send(
            "⚠️ GitHub App not configured.\n\n"
            "Run `/github setup` to add credentials, or set these in your `.env`:\n"
            "  `GITHUB_APP_ID`\n"
            "  `GITHUB_INSTALLATION_ID`\n"
            "  `GITHUB_APP_PRIVATE_KEY_PATH`"
        )
        return

    # ---- subcommands --------------------------------------------------------
    if sub == "status":
        await _cmd_status(client, send)

    elif sub == "repos":
        await _cmd_repos(client, send)

    elif sub == "issues":
        await _cmd_issues(client, args[1:], send)

    elif sub in ("prs", "pr"):
        await _cmd_prs(client, args[1:], send)

    elif sub == "view":
        await _cmd_view(client, args[1:], send)

    elif sub == "diff":
        await _cmd_diff(client, args[1:], send)

    elif sub == "comment":
        await _cmd_comment(client, args[1:], send)

    elif sub == "review":
        await _cmd_review(client, args[1:], send)

    else:
        await send(f"Unknown subcommand: `{sub}`\n\n{HELP_TEXT}")


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

async def _cmd_status(client, send):
    try:
        info = await client.app_info()
        auth = _get_auth()
        token = await auth.get_token()
        await send(
            f"✅ **GitHub App connected**\n"
            f"  Name: `{info.get('name')}`\n"
            f"  Slug: `{info.get('slug')}`\n"
            f"  App ID: `{info.get('id')}`\n"
            f"  Installation ID: `{auth.installation_id}`\n"
            f"  Token: `{token[:8]}...` (auto-refresh enabled)"
        )
    except Exception as exc:
        await send(f"❌ GitHub App error: {exc}")


async def _cmd_repos(client, send):
    try:
        repos = await client.list_repos()
        if not repos:
            await send("No repositories accessible to this installation.")
            return
        lines = [f"📂 **{len(repos)} repositories:**"]
        for r in repos[:20]:
            lines.append(_fmt_repo(r))
        if len(repos) > 20:
            lines.append(f"  ... and {len(repos) - 20} more")
        await send("\n".join(lines))
    except Exception as exc:
        await send(f"❌ Error: {exc}")


async def _cmd_issues(client, args, send):
    if not args:
        await send("Usage: `/github issues <owner/repo>` [open|closed|all]")
        return
    repo = args[0]
    state = args[1] if len(args) > 1 else "open"
    if "/" not in repo:
        await send(f"❌ Invalid repo format. Use `owner/repo` (got `{repo}`).")
        return
    owner, name = repo.split("/", 1)
    try:
        items = await client.list_issues(owner, name, state=state, per_page=15)
        # Filter out PRs
        issues = [i for i in items if "pull_request" not in i]
        if not issues:
            await send(f"No {state} issues in `{repo}`.")
            return
        lines = [f"🐛 **Issues in `{repo}` [{state}]:**"]
        for i in issues[:15]:
            lines.append(_fmt_issue(i))
        await send("\n".join(lines))
    except Exception as exc:
        await send(f"❌ Error: {exc}")


async def _cmd_prs(client, args, send):
    if not args:
        await send("Usage: `/github prs <owner/repo>` [open|closed|all]")
        return
    repo = args[0]
    state = args[1] if len(args) > 1 else "open"
    if "/" not in repo:
        await send(f"❌ Invalid repo format. Use `owner/repo`.")
        return
    owner, name = repo.split("/", 1)
    try:
        prs = await client.list_prs(owner, name, state=state, per_page=15)
        if not prs:
            await send(f"No {state} PRs in `{repo}`.")
            return
        lines = [f"🔀 **Pull Requests in `{repo}` [{state}]:**"]
        for p in prs[:15]:
            lines.append(_fmt_pr(p))
        await send("\n".join(lines))
    except Exception as exc:
        await send(f"❌ Error: {exc}")


async def _cmd_view(client, args, send):
    # args: ["issue"|"pr", "owner/repo", "number"]
    if len(args) < 3:
        await send("Usage: `/github view issue <owner/repo> <number>`\n       `/github view pr <owner/repo> <number>`")
        return
    kind, repo, num_str = args[0].lower(), args[1], args[2]
    if "/" not in repo:
        await send(f"❌ Invalid repo format. Use `owner/repo`.")
        return
    try:
        num = int(num_str)
    except ValueError:
        await send(f"❌ Invalid number: `{num_str}`")
        return
    owner, name = repo.split("/", 1)
    try:
        if kind in ("pr", "pull"):
            data = await client.get_pr(owner, name, num)
            body = data.get("body") or "_No description_"
            await send(
                f"🔀 **PR #{num}: {data['title']}**\n"
                f"  State: {data['state']} | Merged: {bool(data.get('merged_at'))}\n"
                f"  By: {data['user']['login']}\n"
                f"  Branch: `{data['head']['label']}` → `{data['base']['label']}`\n\n"
                f"{body[:800]}"
            )
        else:
            data = await client.get_issue(owner, name, num)
            body = data.get("body") or "_No description_"
            await send(
                f"🐛 **Issue #{num}: {data['title']}**\n"
                f"  State: {data['state']} | Comments: {data.get('comments', 0)}\n"
                f"  By: {data['user']['login']}\n\n"
                f"{body[:800]}"
            )
    except Exception as exc:
        await send(f"❌ Error: {exc}")


async def _cmd_diff(client, args, send):
    if len(args) < 2:
        await send("Usage: `/github diff <owner/repo> <pr_number>`")
        return
    repo, num_str = args[0], args[1]
    if "/" not in repo:
        await send(f"❌ Invalid repo format. Use `owner/repo`.")
        return
    try:
        num = int(num_str)
    except ValueError:
        await send(f"❌ Invalid PR number.")
        return
    owner, name = repo.split("/", 1)
    try:
        diff = await client.get_pr_diff(owner, name, num)
        # Truncate for chat
        snippet = diff[:2000]
        if len(diff) > 2000:
            snippet += f"\n... (truncated, total {len(diff)} chars)"
        await send(f"```diff\n{snippet}\n```")
    except Exception as exc:
        await send(f"❌ Error: {exc}")


async def _cmd_comment(client, args, send):
    if len(args) < 3:
        await send("Usage: `/github comment <owner/repo> <issue_or_pr_number> <text>`")
        return
    repo, num_str = args[0], args[1]
    body = " ".join(args[2:])
    if "/" not in repo:
        await send(f"❌ Invalid repo format. Use `owner/repo`.")
        return
    try:
        num = int(num_str)
    except ValueError:
        await send(f"❌ Invalid number.")
        return
    owner, name = repo.split("/", 1)
    try:
        result = await client.create_issue_comment(owner, name, num, body)
        await send(f"✅ Comment posted: {result.get('html_url', 'done')}")
    except Exception as exc:
        await send(f"❌ Error: {exc}")


async def _cmd_review(client, args, send):
    # /github review owner/repo pr_number APPROVE|REQUEST_CHANGES|COMMENT body...
    if len(args) < 3:
        await send(
            "Usage: `/github review <owner/repo> <pr_number> <APPROVE|REQUEST_CHANGES|COMMENT> <body>`"
        )
        return
    repo, num_str, event = args[0], args[1], args[2].upper()
    body = " ".join(args[3:]) if len(args) > 3 else ""
    if event not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        await send(f"❌ Event must be APPROVE, REQUEST_CHANGES, or COMMENT (got `{event}`).")
        return
    if "/" not in repo:
        await send(f"❌ Invalid repo format. Use `owner/repo`.")
        return
    try:
        num = int(num_str)
    except ValueError:
        await send(f"❌ Invalid PR number.")
        return
    owner, name = repo.split("/", 1)
    try:
        result = await client.submit_pr_review(owner, name, num, body=body, event=event)
        await send(f"✅ Review submitted ({event}): {result.get('html_url', 'done')}")
    except Exception as exc:
        await send(f"❌ Error: {exc}")


# ---------------------------------------------------------------------------
# Setup wizard (writes to .env)
# ---------------------------------------------------------------------------

async def _cmd_setup(send):
    await send(
        "⚙️ **GitHub App Setup**\n\n"
        "Add these to your `.env` file:\n"
        "```\n"
        "GITHUB_APP_ID=<your App ID from GitHub App settings>\n"
        "GITHUB_INSTALLATION_ID=<installation ID>\n"
        "GITHUB_APP_PRIVATE_KEY_PATH=<path to .pem file>\n"
        "# OR inline PEM (replace newlines with \\n):\n"
        "# GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\n"
        "GITHUB_WEBHOOK_SECRET=<optional, for webhook gateway>\n"
        "GITHUB_WEBHOOK_PORT=8765\n"
        "```\n\n"
        "**To find your Installation ID:**\n"
        "1. Go to `github.com/settings/installations`\n"
        "2. Click your app → URL contains the installation ID\n"
        "   e.g. `...installations/12345678` → ID is `12345678`\n\n"
        "After saving `.env`, restart Nexus or run `/github status` to verify."
    )


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP_TEXT = """🐙 **GitHub App Commands:**
  `/github status`                           — connection status
  `/github repos`                            — list accessible repos
  `/github issues <owner/repo>` [open|closed|all]
  `/github prs <owner/repo>` [open|closed|all]
  `/github view issue <owner/repo> <#>`
  `/github view pr <owner/repo> <#>`
  `/github diff <owner/repo> <pr#>`          — show PR diff
  `/github comment <owner/repo> <#> <text>`  — post comment
  `/github review <owner/repo> <pr#> APPROVE|REQUEST_CHANGES|COMMENT <body>`
  `/github setup`                            — show setup instructions"""
