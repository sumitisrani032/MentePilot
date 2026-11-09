import json

from shopchat.worker.main import WorkerSettings, split_jsonl


def test_line_separator_inside_json_does_not_split_a_record() -> None:
    line = json.dumps({"title": "a\u2028b"}, ensure_ascii=False)
    assert [json.loads(item) for item in split_jsonl(f"{line}\n")[:1]] == [{"title": "a\u2028b"}]


def test_long_imports_are_not_killed_by_the_default_time_limit() -> None:
    assert WorkerSettings.job_timeout > 300
