from pathlib import Path

import pytest

from smart_retail.copilot.evaluation import (
    evaluate_copilot_components,
    load_evaluation_cases,
)

PROJECT_ROOT = Path(__file__).parents[1]
EVALUATION_DATASET = PROJECT_ROOT / "data" / "evaluation" / "copilot_eval_v1.jsonl"
KNOWLEDGE_MANIFEST = PROJECT_ROOT / "data" / "knowledge" / "manifest.json"


def test_copilot_v1_component_evaluation_passes() -> None:
    cases = load_evaluation_cases(EVALUATION_DATASET)

    result = evaluate_copilot_components(
        cases,
        KNOWLEDGE_MANIFEST,
        dataset_version="copilot_eval_v1",
    )

    assert result.total_cases == 60
    assert result.retrieval_cases == 30
    assert result.retrieval_recall_at_k >= 0.95
    assert result.retrieval_mrr >= 0.90
    assert result.grounding_accuracy == 1.0
    assert result.tool_contract_accuracy == 1.0
    assert result.approval_policy_accuracy == 1.0
    assert result.pass_rate >= 0.95


def test_copilot_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    path.write_text(
        '{"case_id":"same","category":"approval_policy","tool_name":"set_price",'
        '"role":"admin","expected_allowed":true}\n'
        '{"case_id":"same","category":"approval_policy","tool_name":"set_price",'
        '"role":"operator","expected_allowed":false}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate case_id"):
        load_evaluation_cases(path)
