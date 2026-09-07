"""External I/O transports for tracker adapters.

Adapters use semantic operations. A transport decides how they reach a provider.
The MCP bridge uses JSON over stdin/stdout because MCP connections belong to the
host AI runtime and must not be imported, or have their secrets copied, here.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..errors import (
    ConfigError,
    TrackerAuthenticationError,
    TrackerNotFoundError,
    TrackerPermissionError,
    TrackerThrottledError,
    TrackerUnavailableError,
    UnsupportedCapabilityError,
)


class CommandMCPTransport:
    """Invoke a runtime-owned MCP bridge using one JSON request and response."""

    name = "mcp"

    def __init__(self, command: str | None = None) -> None:
        self.command = command or os.environ.get("LUMOS_MCP_COMMAND", "")

    def connected(self, provider: str | None = None) -> bool:
        return bool(self.command.strip())

    def call(self, provider: str, operation: str, params: dict[str, Any]) -> Any:
        if not self.connected():
            raise TrackerUnavailableError(
                "MCP transport requires a runtime bridge in LUMOS_MCP_COMMAND; see docs/trackers.md"
            )
        request = json.dumps({"provider": provider, "operation": operation, "params": params})
        try:
            completed = subprocess.run(
                shlex.split(self.command), input=request, text=True, capture_output=True, check=False, timeout=120
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TrackerUnavailableError(f"MCP bridge failed: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "bridge returned a non-zero exit status"
            raise TrackerUnavailableError(f"MCP bridge failed: {detail}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise TrackerUnavailableError("MCP bridge returned invalid JSON") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise TrackerUnavailableError(str(payload["error"]))
        return payload.get("result", payload) if isinstance(payload, dict) else payload


class RestTransport:
    """Dependency-free REST transport for all first-party providers."""

    name = "rest"

    def connected(self, provider: str | None = None) -> bool:
        credentials = {
            "github": ("GITHUB_TOKEN", "GH_TOKEN"),
            "jira": ("JIRA_API_TOKEN", "JIRA_TOKEN"),
            "gitlab": ("GITLAB_TOKEN",),
            "azure-devops": ("AZURE_DEVOPS_TOKEN",),
        }
        return any(os.environ.get(name) for name in credentials.get(str(provider), ()))

    def call(self, provider: str, operation: str, params: dict[str, Any]) -> Any:
        handler = getattr(self, f"_{provider.replace('-', '_')}", None)
        if handler is None:
            raise UnsupportedCapabilityError(f"REST transport does not support provider {provider!r}")
        return handler(operation, params)

    def _request(self, method: str, url: str, *, headers: dict[str, str], body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = f"tracker API returned HTTP {exc.code} ({exc.reason})"
            error_type = {
                401: TrackerAuthenticationError,
                403: TrackerPermissionError,
                404: TrackerNotFoundError,
                429: TrackerThrottledError,
            }.get(exc.code, TrackerUnavailableError)
            raise error_type(detail) from exc
        except urllib.error.URLError as exc:
            raise TrackerUnavailableError(f"tracker request failed: {exc.reason}") from exc

    @staticmethod
    def _required(options: dict[str, str], key: str, provider: str) -> str:
        value = str(options.get(key, "")).strip()
        if not value:
            raise ConfigError(f"tracker.options.{key} is required for {provider}")
        return value

    def _github(self, operation: str, params: dict[str, Any]) -> Any:
        options = params["options"]
        repository = self._required(options, "repository", "github")
        issue = urllib.parse.quote(str(params["work_id"]).replace("GH#", "").replace("GH-", "").lstrip("#"), safe="")
        base = str(options.get("api_url", "https://api.github.com")).rstrip("/")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise TrackerAuthenticationError("GitHub REST transport requires GITHUB_TOKEN or GH_TOKEN")
        headers = {
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
            "Content-Type": "application/json", "User-Agent": "lumos-tracker",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        issue_url = f"{base}/repos/{repository}/issues/{issue}"
        if operation == "fetch":
            return self._request("GET", issue_url, headers=headers)
        if operation == "comment":
            return self._comment_once(f"{issue_url}/comments", headers, params)
        if operation == "link_pull_request":
            linked = {**params, "body": f"Pull request: {params['pr_url']}"}
            return self._comment_once(f"{issue_url}/comments", headers, linked)
        if operation == "transition":
            state = "closed" if str(params["state"]).lower() in {"closed", "done", "resolved"} else "open"
            return self._request("PATCH", issue_url, headers=headers, body={"state": state})
        raise UnsupportedCapabilityError(f"GitHub REST operation {operation!r} is unsupported")

    def _jira(self, operation: str, params: dict[str, Any]) -> Any:
        options = params["options"]
        site = self._required(options, "site", "jira").rstrip("/")
        key = urllib.parse.quote(str(params["work_id"]), safe="-")
        token = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_TOKEN")
        if not token:
            raise TrackerAuthenticationError("Jira REST transport requires JIRA_API_TOKEN or JIRA_TOKEN")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        email = os.environ.get("JIRA_EMAIL")
        if email:
            encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        else:
            headers["Authorization"] = f"Bearer {token}"
        issue_url = f"{site}/rest/api/3/issue/{key}"
        if operation == "fetch":
            return self._request("GET", issue_url, headers=headers)
        if operation == "comment":
            url = f"{issue_url}/comment"
            if self._contains_key(url, headers, params["idempotency_key"], "comments"):
                return {"deduplicated": True}
            marked = _marked(params["body"], params["idempotency_key"])
            return self._request("POST", url, headers=headers, body={"body": _adf(marked)})
        if operation == "link_pull_request":
            global_id = f"lumos:{params['idempotency_key']}"
            existing = self._request("GET", f"{issue_url}/remotelink", headers=headers)
            if global_id in json.dumps(existing, sort_keys=True):
                return {"deduplicated": True}
            body = {"globalId": global_id, "object": {"url": params["pr_url"], "title": "Lumos pull request"}}
            return self._request("POST", f"{issue_url}/remotelink", headers=headers, body=body)
        if operation == "transition":
            transitions = self._request("GET", f"{issue_url}/transitions", headers=headers).get("transitions", [])
            wanted = str(params["state"]).casefold()
            match = next((item for item in transitions if str(item.get("name", "")).casefold() == wanted), None)
            if not match:
                raise UnsupportedCapabilityError(f"Jira transition {params['state']!r} is not available")
            body = {"transition": {"id": match["id"]}}
            return self._request("POST", f"{issue_url}/transitions", headers=headers, body=body)
        raise UnsupportedCapabilityError(f"Jira REST operation {operation!r} is unsupported")

    def _gitlab(self, operation: str, params: dict[str, Any]) -> Any:
        options = params["options"]
        host = str(options.get("host", "https://gitlab.com")).rstrip("/")
        project = urllib.parse.quote(self._required(options, "project", "gitlab"), safe="")
        iid = urllib.parse.quote(str(params["work_id"]).replace("GL#", "").replace("GL-", "").lstrip("#"), safe="")
        token = os.environ.get("GITLAB_TOKEN")
        if not token:
            raise TrackerAuthenticationError("GitLab REST transport requires GITLAB_TOKEN")
        headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}
        issue_url = f"{host}/api/v4/projects/{project}/issues/{iid}"
        if operation == "fetch":
            return self._request("GET", issue_url, headers=headers)
        if operation in {"comment", "link_pull_request"}:
            body = params["body"] if operation == "comment" else f"Merge/pull request: {params['pr_url']}"
            return self._comment_once(f"{issue_url}/notes", headers, {**params, "body": body})
        if operation == "transition":
            state = "close" if str(params["state"]).lower() in {"closed", "done", "resolved"} else "reopen"
            return self._request("PUT", issue_url, headers=headers, body={"state_event": state})
        raise UnsupportedCapabilityError(f"GitLab REST operation {operation!r} is unsupported")

    def _azure_devops(self, operation: str, params: dict[str, Any]) -> Any:
        options = params["options"]
        org = urllib.parse.quote(self._required(options, "organization", "azure-devops"), safe="")
        project = urllib.parse.quote(self._required(options, "project", "azure-devops"), safe="")
        raw_id = str(params["work_id"])
        work_id = urllib.parse.quote(raw_id.split("#")[-1].split("-")[-1], safe="")
        token = os.environ.get("AZURE_DEVOPS_TOKEN")
        if not token:
            raise TrackerAuthenticationError("Azure DevOps REST transport requires AZURE_DEVOPS_TOKEN")
        encoded = base64.b64encode(f":{token}".encode()).decode()
        headers = {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}
        base = str(options.get("base_url", "https://dev.azure.com")).rstrip("/")
        item_url = f"{base}/{org}/{project}/_apis/wit/workitems/{work_id}"
        if operation == "fetch":
            return self._request("GET", f"{item_url}?$expand=relations&api-version=7.1", headers=headers)
        if operation == "comment":
            url = f"{item_url}/comments?api-version=7.1-preview.4"
            if self._contains_key(url, headers, params["idempotency_key"], "comments"):
                return {"deduplicated": True}
            body = {"text": _marked(params["body"], params["idempotency_key"])}
            return self._request("POST", url, headers=headers, body=body)
        patch_headers = {**headers, "Content-Type": "application/json-patch+json"}
        if operation == "link_pull_request":
            current = self._request("GET", f"{item_url}?$expand=relations&api-version=7.1", headers=headers)
            if any(item.get("url") == params["pr_url"] for item in current.get("relations", []) or []):
                return {"deduplicated": True}
            body = [{"op": "add", "path": "/relations/-", "value": {"rel": "Hyperlink", "url": params["pr_url"]}}]
            return self._request("PATCH", f"{item_url}?api-version=7.1", headers=patch_headers, body=body)
        if operation == "transition":
            body = [{"op": "add", "path": "/fields/System.State", "value": params["state"]}]
            return self._request("PATCH", f"{item_url}?api-version=7.1", headers=patch_headers, body=body)
        raise UnsupportedCapabilityError(f"Azure DevOps REST operation {operation!r} is unsupported")

    def _contains_key(
        self, url: str, headers: dict[str, str], idempotency_key: str, collection_key: str | None = None
    ) -> bool:
        payload = self._request("GET", url, headers=headers)
        if collection_key and isinstance(payload, dict):
            payload = payload.get(collection_key, [])
        return idempotency_key in json.dumps(payload, sort_keys=True)

    def _comment_once(self, url: str, headers: dict[str, str], params: dict[str, Any]) -> Any:
        key = str(params["idempotency_key"])
        if self._contains_key(url, headers, key):
            return {"deduplicated": True}
        return self._request("POST", url, headers=headers, body={"body": _marked(params["body"], key)})


def _adf(text: str) -> dict[str, Any]:
    content = [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]
    return {"type": "doc", "version": 1, "content": content}


def _marked(text: str, idempotency_key: str) -> str:
    return f"{text}\n\n<!-- lumos:{idempotency_key} -->"


def create_transport(name: str):
    normalized = str(name or "mcp").strip().lower()
    if normalized == "mcp":
        return CommandMCPTransport()
    if normalized == "rest":
        return RestTransport()
    raise ConfigError(f"unknown tracker transport {name!r}; expected 'mcp' or 'rest'")
