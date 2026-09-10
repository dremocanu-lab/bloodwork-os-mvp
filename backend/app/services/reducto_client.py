"""Thin HTTP client for the real Reducto API.

Verified against the live API (platform.reducto.ai) with synthetic
Romanian medical documents before this module was written — see the
PR/commit description for the exact endpoints, request/response shapes,
and error formats observed. Nothing here is guessed from documentation
alone.

Endpoints used (all under https://platform.reducto.ai, `Authorization:
Bearer <REDUCTO_API_KEY>`):

    POST /upload            multipart file -> {"file_id": "reducto://..."}
    POST /classify           {"input", "classification_schema"} -> sync,
                              {"result": {"category"}, "response_confidence":
                              {"categories": [{"category","confidence",
                              "criteria_confidence"}]}, "usage", "duration"}
    POST /parse               {"input", ...} -> sync for small documents,
                              {"result": {"chunks": [{"content","blocks":
                              [{"type","bbox","content","confidence",...}]}]}}
    POST /extract             {"input","instructions":{"schema"},
                              "settings":{"citations":{"enabled"}}} ->
                              {"result": {field: {"value","citations":[...]}}}
                              when citations are enabled; plain values
                              otherwise.
    POST /split                {"document_url","split_description":[{"name",
                              "description"}]} -> {"result": {"splits":
                              [{"name","pages":[...],"conf":"high"|"low"}]}}
    GET  /job/{job_id}        poll an async job (Pending/InProgress/
                              Completing/Completed/Failed)

All of the above returned a complete `result` inline within the request
timeout for the (1-9 page) documents tested. Reducto's own docs recommend
the `_async` variants + polling for large documents (>100 pages); this
client submits synchronously first and falls back to polling only if the
sync response comes back without a `result` (see `_maybe_await_job`),
rather than always paying the polling round-trip latency.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests

BASE_URL = "https://platform.reducto.ai"
DEFAULT_TIMEOUT_S = 180
JOB_POLL_INTERVAL_S = 2.0
JOB_POLL_BUDGET_S = 300


class ReductoError(RuntimeError):
    """Base class for all Reducto integration failures."""


class ReductoAuthError(ReductoError):
    """401 — REDUCTO_API_KEY missing/invalid/revoked. Never retryable."""


class ReductoNotFoundError(ReductoError):
    """404 — file_id/job_id unknown or expired. Never retryable."""


class ReductoTimeoutError(ReductoError):
    """The request (or job polling budget) timed out. Retryable."""


class ReductoServerError(ReductoError):
    """5xx from Reducto. Retryable."""


class ReductoRateLimitedError(ReductoError):
    """429 from Reducto. Retryable (with backoff)."""


class ReductoMalformedResponseError(ReductoError):
    """2xx but the response body didn't have the shape we expect."""


RETRYABLE_ERRORS = (ReductoTimeoutError, ReductoServerError, ReductoRateLimitedError)


@dataclass
class ReductoConfig:
    api_key: str
    base_url: str = BASE_URL
    timeout_s: int = DEFAULT_TIMEOUT_S


def _raise_for_response(response: requests.Response) -> None:
    if response.ok:
        return

    try:
        body = response.json()
        message = (body.get("error") or {}).get("message") or body.get("detail") or response.text
    except Exception:
        message = response.text

    status = response.status_code
    if status == 401:
        raise ReductoAuthError(f"Reducto authentication failed: {message}")
    if status == 404:
        raise ReductoNotFoundError(f"Reducto resource not found: {message}")
    if status == 429:
        raise ReductoRateLimitedError(f"Reducto rate limit exceeded: {message}")
    if 500 <= status < 600:
        raise ReductoServerError(f"Reducto server error ({status}): {message}")
    raise ReductoError(f"Reducto request failed ({status}): {message}")


class ReductoClient:
    """One instance per request/job is fine — this holds no mutable state
    beyond the API key and an optional `requests.Session` for connection
    reuse."""

    def __init__(self, api_key: str | None = None, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        self.api_key = (api_key or os.getenv("REDUCTO_API_KEY", "")).strip()
        if not self.api_key:
            raise ReductoAuthError("REDUCTO_API_KEY is not configured.")
        self.timeout_s = timeout_s
        self._session = requests.Session()

    def _headers(self, json_request: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if json_request:
            headers["Content-Type"] = "application/json"
        return headers

    def _post_json(self, path: str, payload: dict[str, Any], timeout_s: int | None = None) -> dict[str, Any]:
        try:
            response = self._session.post(
                f"{BASE_URL}{path}",
                headers=self._headers(json_request=True),
                json=payload,
                timeout=timeout_s or self.timeout_s,
            )
        except requests.Timeout as exc:
            raise ReductoTimeoutError(f"Reducto request to {path} timed out.") from exc
        except requests.RequestException as exc:
            raise ReductoServerError(f"Reducto request to {path} failed: {exc}") from exc

        _raise_for_response(response)

        try:
            return response.json()
        except ValueError as exc:
            raise ReductoMalformedResponseError(f"Reducto {path} returned non-JSON body.") from exc

    # -- Upload ------------------------------------------------------------

    def upload(self, file_path: str, filename: str | None = None) -> str:
        """Uploads a local file, returns its `reducto://...` file_id."""
        try:
            with open(file_path, "rb") as fh:
                files = {"file": (filename or os.path.basename(file_path), fh)}
                response = self._session.post(
                    f"{BASE_URL}/upload",
                    headers=self._headers(json_request=False),
                    files=files,
                    timeout=self.timeout_s,
                )
        except requests.Timeout as exc:
            raise ReductoTimeoutError("Reducto upload timed out.") from exc
        except requests.RequestException as exc:
            raise ReductoServerError(f"Reducto upload failed: {exc}") from exc

        _raise_for_response(response)

        try:
            file_id = response.json()["file_id"]
        except (ValueError, KeyError) as exc:
            raise ReductoMalformedResponseError("Reducto /upload response had no file_id.") from exc

        return file_id

    # -- Classify (synchronous) ---------------------------------------------

    def classify(self, file_id: str, classification_schema: list[dict[str, Any]]) -> dict[str, Any]:
        body = self._post_json("/classify", {"input": file_id, "classification_schema": classification_schema})

        if "result" not in body or "category" not in body.get("result", {}):
            raise ReductoMalformedResponseError("Reducto /classify response missing result.category.")

        return body

    # -- Parse ---------------------------------------------------------------

    def parse(self, file_id: str, table_output_format: str = "md") -> dict[str, Any]:
        body = self._post_json(
            "/parse",
            {"input": file_id, "formatting": {"table_output_format": table_output_format}},
        )
        body = self._maybe_await_job(body)

        if "result" not in body or "chunks" not in body.get("result", {}):
            raise ReductoMalformedResponseError("Reducto /parse response missing result.chunks.")

        return body

    # -- Extract ---------------------------------------------------------------

    def extract(
        self,
        file_id: str,
        schema: dict[str, Any],
        citations: bool = True,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        instructions: dict[str, Any] = {"schema": schema}
        if system_prompt:
            instructions["system_prompt"] = system_prompt

        payload: dict[str, Any] = {
            "input": file_id,
            "instructions": instructions,
        }
        if citations:
            payload["settings"] = {"citations": {"enabled": True, "numerical_confidence": True}}

        body = self._post_json("/extract", payload, timeout_s=max(self.timeout_s, 240))
        body = self._maybe_await_job(body)

        if "result" not in body:
            raise ReductoMalformedResponseError("Reducto /extract response missing result.")

        return body

    # -- Split -----------------------------------------------------------------

    def split(self, file_id: str, split_description: list[dict[str, Any]]) -> dict[str, Any]:
        body = self._post_json(
            "/split",
            {"document_url": file_id, "split_description": split_description},
            timeout_s=max(self.timeout_s, 240),
        )
        body = self._maybe_await_job(body)

        if "result" not in body or "splits" not in body.get("result", {}):
            raise ReductoMalformedResponseError("Reducto /split response missing result.splits.")

        return body

    # -- Async job polling -------------------------------------------------------

    def get_job(self, job_id: str) -> dict[str, Any]:
        try:
            response = self._session.get(
                f"{BASE_URL}/job/{job_id}",
                headers=self._headers(),
                timeout=self.timeout_s,
            )
        except requests.Timeout as exc:
            raise ReductoTimeoutError(f"Polling Reducto job {job_id} timed out.") from exc
        except requests.RequestException as exc:
            raise ReductoServerError(f"Polling Reducto job {job_id} failed: {exc}") from exc

        _raise_for_response(response)

        try:
            return response.json()
        except ValueError as exc:
            raise ReductoMalformedResponseError(f"Reducto /job/{job_id} returned non-JSON body.") from exc

    def _maybe_await_job(self, body: dict[str, Any]) -> dict[str, Any]:
        """Every sync call tested returned `result` inline. Reducto's own
        docs say large documents may not, and always return a `job_id` —
        poll GET /job/{id} in that case rather than treating a slow job as
        a malformed response."""
        if "result" in body or "job_id" not in body:
            return body

        job_id = body["job_id"]
        deadline = time.monotonic() + JOB_POLL_BUDGET_S

        while time.monotonic() < deadline:
            time.sleep(JOB_POLL_INTERVAL_S)
            job = self.get_job(job_id)
            status = job.get("status")

            if status == "Completed":
                return job
            if status == "Failed":
                raise ReductoError(f"Reducto job {job_id} failed: {job.get('error')}")
            # Pending / InProgress / Completing -> keep polling.

        raise ReductoTimeoutError(f"Reducto job {job_id} did not complete within {JOB_POLL_BUDGET_S}s.")
