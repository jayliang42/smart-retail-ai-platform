"""Command-line entry point for repeatable inventory intelligence evaluation."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from smart_retail.analytics.anomalies import (
    InventoryRiskRulesDetector,
    StockoutOnlyDetector,
)
from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.analytics.evaluation import evaluate_anomaly_detector, evaluate_forecaster
from smart_retail.analytics.forecasting import LastValueForecaster, TrailingMeanForecaster


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate inventory intelligence baselines")
    parser.add_argument("dataset", type=Path, help="versioned labeled daily retail CSV")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dataset_path = cast(Path, args.dataset)
    loaded = load_daily_metrics(dataset_path)
    detectors = (StockoutOnlyDetector(), InventoryRiskRulesDetector())
    evaluations = [
        asdict(evaluate_anomaly_detector(loaded.records, detector))
        for detector in detectors
    ]
    forecasters = (LastValueForecaster(), TrailingMeanForecaster())
    forecast_evaluations = [
        asdict(evaluate_forecaster(loaded.records, forecaster))
        for forecaster in forecasters
    ]
    output = {
        "dataset": str(dataset_path),
        "data_quality": asdict(loaded.report),
        "anomaly_evaluations": evaluations,
        "forecast_evaluations": forecast_evaluations,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
