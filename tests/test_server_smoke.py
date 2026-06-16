"""Smoke tests: tools register with correct annotations, and the safety gates
behave end-to-end through the MCP layer (no network)."""

from __future__ import annotations

import pytest

from kaggle_mcp import server

EXPECTED_TOOLS = {
    "kaggle_whoami", "kaggle_status",
    "kaggle_list_competitions", "kaggle_get_competition", "kaggle_competition_leaderboard",
    "kaggle_download_competition_files", "kaggle_accept_competition_rules",
    "kaggle_preview_submission", "kaggle_submit_to_competition",
    "kaggle_list_submissions", "kaggle_get_submission_score",
    "kaggle_search_datasets", "kaggle_get_dataset_metadata", "kaggle_download_dataset",
    "kaggle_create_dataset", "kaggle_version_dataset", "kaggle_dataset_status",
    "kaggle_delete_dataset",
    "kaggle_list_kernels", "kaggle_pull_kernel", "kaggle_push_kernel",
    "kaggle_kernel_status", "kaggle_kernel_output",
    "kaggle_list_models", "kaggle_get_model", "kaggle_download_model", "kaggle_delete_model",
}


async def test_all_tools_register():
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {missing}"


async def test_every_tool_has_description_and_annotations():
    tools = await server.mcp.list_tools()
    for t in tools:
        assert t.description, f"{t.name} has no description"
        assert t.annotations is not None, f"{t.name} has no annotations"


async def test_submit_is_marked_destructive():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    submit = tools["kaggle_submit_to_competition"]
    assert submit.annotations.destructiveHint is True
    assert submit.annotations.idempotentHint is False


async def test_search_is_marked_read_only():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert tools["kaggle_search_datasets"].annotations.readOnlyHint is True


async def test_submit_rejects_without_valid_token():
    result = await server.mcp.call_tool(
        "kaggle_submit_to_competition",
        {"competition": "titanic", "file_path": "/nope.csv",
         "message": "x", "confirm_token": "bogus"},
    )
    # FastMCP returns (content, structured_result); the structured dict carries our envelope.
    structured = result[1] if isinstance(result, tuple) else result
    text = str(structured)
    assert "confirm_token" in text or "isError" in text


async def test_resources_and_prompts_register():
    resources = await server.mcp.list_resource_templates()
    prompts = await server.mcp.list_prompts()
    assert any("leaderboard" in str(r.uriTemplate) for r in resources)
    assert {p.name for p in prompts} >= {"kaggle_eda", "kaggle_submit_checklist"}
