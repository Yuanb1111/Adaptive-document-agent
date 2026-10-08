"""Offline source-first acceptance report; never invokes a model or guesses scores.

Source checklists and output reviews live outside Git. A locked checklist must
precede generation. This helper reports reviewed quality separately from exports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DIMENSIONS = ("number", "unit", "period", "direction", "support")
STATUSES = {"unchecked", "represented", "incorrect", "omitted", "disclosed"}


def add_accuracy_checks(row: dict, counts: dict, *, required: bool) -> tuple[int, bool]:
    checks = row.get("checks", {})
    complete = not required or set(checks) == set(DIMENSIONS)
    failures = 0
    for dim, value in checks.items():
        if dim not in DIMENSIONS:
            raise ValueError("Unknown accuracy dimension")
        correct, denominator = value["correct"], value["checked"]
        if (type(correct) is not int or type(denominator) is not int
                or correct < 0 or correct > denominator):
            raise ValueError("Invalid accuracy counts")
        counts[dim]["correct"] += correct
        counts[dim]["checked"] += denominator
        failures += denominator - correct
        if denominator == 0 and not str(value.get("not_applicable_reason", "")).strip():
            complete = False
    return failures, complete


def assess_review(facts: list[dict], review: dict, *, run_verified: bool) -> dict:
    """Apply an explicit reviewer rubric, not semantic/numeric string matching."""
    expected = {fact["fact_id"]: fact for fact in facts}
    if len(expected) != len(facts) or not facts:
        raise ValueError("Expected fact IDs must be unique and non-empty")
    rows = review.get("facts", [])
    ids = [row["fact_id"] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) - expected.keys():
        raise ValueError("Duplicate or unknown review fact ID")
    counts = {dim: {"correct": 0, "checked": 0} for dim in DIMENSIONS}
    checked = errors = failed_checks = omissions = disclosed = 0
    complete_checks = True
    for row in rows:
        status = row.get("status", "unchecked")
        if status not in STATUSES:
            raise ValueError("Unknown review status")
        if status == "unchecked":
            continue
        checked += 1
        if status in {"represented", "incorrect", "disclosed"} and not row.get("output_locators"):
            raise ValueError("Reviewed output claims require concrete locators")
        has_missing_component = bool(row.get("missing_content") or row.get("decision_impact"))
        if status in {"omitted", "disclosed"} or has_missing_component:
            if not str(row.get("missing_content", "")).strip() or not str(row.get("decision_impact", "")).strip():
                raise ValueError("An omission needs missing content and its decision impact")
            if status == "represented":
                raise ValueError("A represented fact cannot have a missing component")
            if expected[row["fact_id"]].get("material", True):
                omissions += status != "disclosed"
                disclosed += status == "disclosed"
        failed, complete = add_accuracy_checks(row, counts,
            required=status in {"represented", "incorrect", "disclosed"})
        failed_checks += failed
        complete_checks = complete_checks and complete
        errors += status == "incorrect" or failed > 0
    additional_rows = review.get("additional_claims", [])
    extra_ids = [row["fact_id"] for row in additional_rows]
    if len(extra_ids) != len(set(extra_ids)) or set(extra_ids) & expected.keys():
        raise ValueError("Additional claims need distinct IDs outside the source checklist")
    reviewed_extra_errors = 0
    for row in additional_rows:
        if row.get("status") not in {"represented", "incorrect"}:
            raise ValueError("Additional claims must refer to reviewed output assertions")
        if not row.get("output_locators") or not row.get("source_pages"):
            raise ValueError("Additional claims need output locators and original physical pages")
        failed, complete = add_accuracy_checks(row, counts, required=True)
        failed_checks += failed
        complete_checks = complete_checks and complete
        reviewed_extra_errors += row["status"] == "incorrect" or failed > 0
    additional_errors = review.get("additional_claim_errors")
    if additional_errors is not None:
        if type(additional_errors) is not int or additional_errors < 0:
            raise ValueError("Invalid additional claim error count")
        if additional_rows and additional_errors != reviewed_extra_errors:
            raise ValueError("Additional error count does not match reviewed claims")
        if additional_errors and not additional_rows:
            complete_checks = False  # Missing error denominators cannot certify accuracy.
        errors += additional_errors
    elif additional_rows:
        errors += reviewed_extra_errors
    ready = (run_verified and complete_checks and checked == len(expected)
             and review.get("source_review_complete") is True
             and review.get("output_claim_review_complete") is True
             and additional_errors is not None
             and all(counts[dim]["checked"] > 0 for dim in DIMENSIONS))
    gate = "failed" if errors or omissions else "passed" if ready else "pending"
    pending_reasons = []
    if not run_verified:
        pending_reasons.append("Source, analysis JSON and PPT correspondence is unverified")
    if checked < len(expected):
        pending_reasons.append("Source checklist contains unchecked items")
    if review.get("source_review_complete") is not True:
        pending_reasons.append("Broader source-section review is incomplete")
    if review.get("output_claim_review_complete") is not True or additional_errors is None:
        pending_reasons.append("Review of additional important output claims is incomplete")
    if not complete_checks or any(counts[dim]["checked"] == 0 for dim in DIMENSIONS):
        pending_reasons.append("Accuracy dimensions are incomplete or have zero denominators")
    minutes = review.get("human_editing_minutes")
    if minutes is not None and (type(minutes) not in {float, int}
                               or not math.isfinite(minutes) or minutes < 0):
        raise ValueError("Editing time must be measured, non-negative or null")
    return dict(fact_gate=gate, expected_items=len(expected), reviewed_items=checked,
                unchecked_items=len(expected)-checked, accuracy=counts,
                detected_errors=errors, failed_accuracy_checks=failed_checks,
                additional_reviewed_claims=len(additional_rows),
                undisclosed_material_omissions=omissions,
                specifically_disclosed_material_omissions=disclosed,
                human_editing_minutes=minutes,
                usefulness_status="not_measured" if minutes is None else "editing_time_recorded",
                pending_reasons=pending_reasons,
                independent_human_review=review.get("independent_human_review", False))


def checked_baseline(sample: dict) -> dict:
    path = Path(sample["checklist_path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sample["checklist_sha256"]:
        raise ValueError("Locked source checklist has changed")
    if hashlib.sha256(Path(sample["source_path"]).read_bytes()).hexdigest() != sample["source_sha256"]:
        raise ValueError("Source PDF has changed")
    baseline = json.loads(raw)
    if baseline["source_sha256"] != sample["source_sha256"]:
        raise ValueError("Checklist/source identity mismatch")
    return baseline


def reviewed_artifacts_match(folder: Path, review: dict) -> bool:
    """A review cannot certify different JSON/PPT bytes under the same names."""
    recorded = review.get("reviewed_artifacts", {})
    for filename in ("analysis.json", "presentation.pptx"):
        path = folder / filename
        if not recorded.get(filename) or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != recorded[filename]:
            return False
    return True


def collect_report(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest["samples"]:
        raise ValueError("An acceptance cohort must contain source samples")
    out = manifest_path.parent
    samples = []
    for sample in manifest["samples"]:
        baseline = checked_baseline(sample)
        folder = out / "runs" / sample["sample_id"]
        if manifest.get("generation_attempt", 1) > 1:
            folder = folder / f"attempt-{manifest['generation_attempt']}"
        start_path = folder / "started.json"
        finished_path = folder / "finished.json"
        started = json.loads(start_path.read_text(encoding="utf-8")) if start_path.exists() else None
        finished = json.loads(finished_path.read_text(encoding="utf-8")) if finished_path.exists() else None
        if started:
            if datetime.fromisoformat(started["started_at"]) <= datetime.fromisoformat(baseline["locked_before_generation_at"]):
                raise ValueError("Source checklist was not locked before generation")
            if started["source_sha256"] != sample["source_sha256"] or started["checklist_sha256"] != sample["checklist_sha256"]:
                raise ValueError("Generation used a different source/checklist")
            if started["code_version"] != manifest["baseline_code_version"] or started["model_settings"] != manifest["model_settings"]:
                raise ValueError("Frozen code or model settings mismatch")
        review_path = out / "reviews" / (sample["sample_id"] + "-output-review.json")
        review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else {}
        review_by_id = {row["fact_id"]: row for row in review.get("facts", [])}
        # Real-file correspondence is supplied by an explicit reviewed run record,
        # never inferred from filenames, timestamps or successful export alone.
        record_path = folder / "run-record.json"
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
        run_verified = bool(started and finished and finished["status"] == "generated"
                            and record.get("real_file_verified") is True
                            and record.get("file_id") == sample["source_sha256"]
                            and record.get("code_version") == manifest["baseline_code_version"]
                            and record.get("pipeline_version") == manifest.get("pipeline_version")
                            and record.get("dataset_role") == "holdout"
                            and record.get("run_mode") == manifest["run_mode"]
                            and reviewed_artifacts_match(folder, review))
        if sample.get("historical_matches") or sample.get("dataset_role") != "holdout":
            run_verified = False
        run_status = (finished["status"] if finished else
                      "running" if started and manifest["generation_status"] == "running" else
                      "unfinished" if started else "not_started")
        samples.append(dict(sample_id=sample["sample_id"], name=sample["name"], industry=sample["industry"],
            official_url=sample["official_url"], source_sha256=sample["source_sha256"],
            page_count=sample["page_count"], independence_status=sample["independence_status"],
            run_status=run_status,
            elapsed_seconds=finished.get("elapsed_seconds") if finished else None,
            model_calls=finished.get("model_calls") if finished else None,
            failure_class=finished.get("failure_class") if finished else None,
            exports=finished.get("exports", []) if finished else [],
            review_scope=review.get("review_scope", "Not reviewed"),
            layout_findings=review.get("layout_findings", []),
            usefulness_notes=review.get("usefulness_notes", ""),
            facts=[{**fact, "output_review": review_by_id.get(fact["fact_id"], {})} for fact in baseline["facts"]],
            additional_claims=review.get("additional_claims", []),
            review=assess_review(baseline["facts"], review, run_verified=run_verified)))
    return dict(created_at=datetime.now(timezone.utc).isoformat(),
                code_version=manifest["baseline_code_version"], pipeline_version=manifest.get("pipeline_version"),
                model_settings=manifest["model_settings"], status=manifest["generation_status"],
                blocker=manifest.get("generation_blocker") if manifest["generation_status"].startswith("blocked") else None,
                generation_attempt=manifest.get("generation_attempt", 1), renderer=manifest.get("renderer"), samples=samples,
                acceptance_passed=False if any(s["review"]["fact_gate"] != "passed" for s in samples) else True,
                human_usefulness_complete=all(s["review"]["human_editing_minutes"] is not None for s in samples))


def write_report(report: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "business-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "source-checklist.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample", "fact_id", "source_pdf_pages", "source_expectation", "omission_impact", "output_status"])
        for sample in report["samples"]:
            for fact in sample["facts"]:
                writer.writerow([csv_text(value) for value in
                                 [sample["name"], fact["fact_id"], ",".join(map(str, fact["pages"])),
                                  fact["expected"], fact["omission_impact"], fact["output_review"].get("status", "unchecked")]])
    esc = lambda value: html.escape(str(value), quote=True)
    generated = sum(s["run_status"] == "generated" for s in report["samples"])
    total = len(report["samples"])
    fact_count = sum(len(s["facts"]) for s in report["samples"])
    headline = ("事实验收达到所设试点门槛" if report["acceptance_passed"] else
                "已发现错误或重大遗漏，未通过" if any(s["review"]["fact_gate"] == "failed" for s in report["samples"])
                else "验收尚未完成")
    parts = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>独立样本业务验收</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1120px;margin:36px auto;padding:0 24px;color:#192335;background:#fff}h1{font-size:30px}h2{margin-top:44px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #dce2e9;padding:12px 10px}th{background:#f2f5f8}code{overflow-wrap:anywhere}a{color:#2057a5}.notice{border-left:4px solid #bd5a20;padding:10px 18px;background:#fff6ee}small{color:#526074}li{margin:12px 0}@media(max-width:700px){body{padding:0 14px}table{font-size:12px}th,td{padding:8px 5px}}</style>",
        "<h1>独立样本业务验收基线</h1>",
        f"<div class='notice'><b>状态：{headline}。</b> {total}份原文及{fact_count}项源文清单已锁定。当前已生成分析 {generated}/{total}。流水线状态：{esc(report['status'])}。{esc(report.get('blocker') or '')}</div>",
        f"<p>固定代码：<code>{esc(report['code_version'])}</code><br>固定模型设置：<code>{esc(json.dumps(report['model_settings'], ensure_ascii=False))}</code>。本轮尝试：{esc(report['generation_attempt'])}。</p>",
        f"<p>独立人工复核和人工修改时间按实际记录报告。哈希独立性仅覆盖已检查历史，不能证明其他环境从未调试。PPT渲染环境：{esc(report.get('renderer') or '未执行')}。</p>",
        "<table><tr><th>样本 / 行业</th><th>全文页数</th><th>本轮运行</th><th>耗时 / 模型调用</th><th>事实核对</th><th>人工改稿</th></tr>"]
    for sample in report["samples"]:
        minutes = sample['review']['human_editing_minutes']
        url = sample['official_url']
        source_link = (f"<a href='{esc(url)}'>{esc(sample['name'])}</a>"
                       if urlsplit(url).scheme.lower() in {'http', 'https'} else esc(sample['name']))
        seconds = sample.get('elapsed_seconds')
        duration = '未完成' if seconds is None else f'{seconds / 60:.1f}分钟'
        calls = sample.get('model_calls')
        parts.append(f"<tr><td>{source_link}<br><small>{esc(sample['industry'])}</small></td><td>{sample['page_count']}</td><td>{esc(sample['run_status'])}</td><td>{esc(duration)}<br>{esc('未知' if calls is None else str(calls)+'次调用')}</td><td>{sample['review']['reviewed_items']} / {sample['review']['expected_items']}<br>{esc(sample['review']['fact_gate'])}</td><td>{esc('未测量' if minutes is None else str(minutes)+'分钟')}</td></tr>")
    parts.append("</table><p><small>认证失败属于配置问题，不能计作模型业务准确性错误或通过。上一轮记录保留。导出成功与业务事实验收分别记录；0/0不显示为100%准确。</small></p>")
    for sample in report["samples"]:
        parts.append(f"<h2>{esc(sample['name'])}</h2><small>源文件SHA-256：<code>{esc(sample['source_sha256'])}</code></small><ol>")
        for fact in sample["facts"]:
            pages = ", ".join(map(str, fact["pages"]))
            row = fact['output_review']
            locators = "; ".join(map(str, row.get('output_locators', [])))
            parts.append(f"<li>{esc(fact['expected'])}<br><small>PDF物理页 {esc(pages)}。遗漏影响：{esc(fact['omission_impact'])}。输出核对：{esc(row.get('status','unchecked'))}。输出位置：{esc(locators or '未记录')}。{esc(row.get('notes',''))}</small></li>")
        parts.append("</ol>")
        if sample.get("additional_claims"):
            parts.append("<h3>输出中新增的重要事实核对</h3><ul>")
            for claim in sample['additional_claims']:
                parts.append(f"<li>{esc(claim.get('claim', claim['fact_id']))}<br><small>状态：{esc(claim['status'])}。原文物理页：{esc(claim['source_pages'])}。输出位置：{esc(claim['output_locators'])}。{esc(claim.get('notes',''))}</small></li>")
            parts.append("</ul>")
        parts.append("<table><tr><th>核对维度</th><th>正确 / 已检查</th></tr>")
        for dim in DIMENSIONS:
            count = sample['review']['accuracy'][dim]
            score = f"{count['correct']} / {count['checked']}" if count['checked'] else "未核对（0 / 0）"
            parts.append(f"<tr><td>{esc(dim)}</td><td>{esc(score)}</td></tr>")
        parts.append("</table>")
        if sample['review'].get('pending_reasons'):
            parts.append("<p>未完成事项：" + esc("；".join(sample['review']['pending_reasons'])) + "。</p>")
        parts.append("<p>实际核对范围：" + esc(sample.get('review_scope', 'Not reviewed')) + "。</p>")
        if sample.get('layout_findings'):
            parts.append("<p>排版检查：" + esc("；".join(sample['layout_findings'])) + "。</p>")
        if sample.get('usefulness_notes'):
            parts.append("<p>使用判断：" + esc(sample['usefulness_notes']) + "。</p>")
    parts.append("<h2>验收方法与边界</h2><p>原文清单锁定在生成之前。逐项核对数值、单位、期间、方向和原文支持，记录具体遗漏及其判断影响，再对照源文JSON与PPT。人工改稿时间由使用者实际计时。</p><p>源文清单是试点最低检查范围；尚无已确认失败但完整章节或输出重要结论未审完时，事实验收为pending；已发现错误或未具体披露的重大遗漏时为failed。后续覆盖修改以真实错误与遗漏为依据。用于修补的样本转为回归样本，另留新文件验收。错误项与失败核对次数分别统计，同一项多个维度出错不会冒充多个独立错误。</p></html>")
    (output / "business-acceptance.html").write_text("\n".join(parts), encoding="utf-8")


def csv_text(value: Any) -> str:
    """Keep untrusted source text inert when a reviewer opens the CSV in Excel."""
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = collect_report(args.cohort)
    write_report(report, args.output or args.cohort.parent)
    print(f"Prepared {len(report['samples'])} samples; acceptance_passed={report['acceptance_passed']}")


if __name__ == "__main__":
    main()
