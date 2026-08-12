import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lambdas" / "auto_fix" / "handler.py"

spec = importlib.util.spec_from_file_location("auto_fix_handler", MODULE_PATH)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)


def test_build_iam_action_strips_cloudtrail_version_suffixes() -> None:
    assert handler._build_iam_action("cloudfront.amazonaws.com", "UntagResource2020_05_31") == "cloudfront:UntagResource"
    assert handler._build_iam_action("s3.amazonaws.com", "PutObject20240101") == "s3:PutObject"
