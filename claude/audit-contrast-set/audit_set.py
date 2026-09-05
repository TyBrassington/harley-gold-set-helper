#!/usr/bin/env python3
"""One-set-at-a-time audit helper for HARLEY v6 contrast sets.

Subcommands
  render  CANDIDATE_ID [--run RUN_ROOT] [--show-pipeline]
          Print one set as markdown: header, SIMILARITY, plan facts (H and S),
          five prompts. Pipeline judge verdicts are hidden unless --show-pipeline.
  record  CANDIDATE_ID --reviewer NAME --verdict-json FILE|-  [--run RUN_ROOT]
          Validate a verdict object and write
          <run_root>/audit/verdicts/<candidate_id>.<reviewer>.json
  next    --run RUN_ROOT --reviewer NAME [--human-verify-only] [--family F] [--n K]
          Print the next K candidate_ids in this run without a verdict from NAME.
  status  --run RUN_ROOT [--reviewer NAME] [--csv OUT]
          Count verdicts per reviewer; optionally export a merged CSV.
  rubric  Print the path of the rubric to read.

Run roots are looked up under RUNS_DIR (default: the wildchat_candidate_mining_2
runs directory). Without --run, `render` and `record` search every finished run
root whose final manifest says pipeline_version v6 (the same candidate_id recurs
in older v3/v5 roots for the same anchor). --run accepts a bare run-root name.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

RUNS_DIR = pathlib.Path(
    os.environ.get(
        "HARLEY_RUNS_DIR",
        "/local-scratch/localhome/wgb/behavior-latent-library/wildchat_candidate_mining_2/runs",
    )
)
RUBRIC_CANDIDATES = [
    RUNS_DIR / "audit_kit_v6" / "rubric_v6.md",
    pathlib.Path(__file__).resolve().parent / "rubric_v6.md",
]
ROLES = ["misaligned_target", "aligned_control", "hard_negative", "style_control", "paraphrase_target"]
LETTER = {"misaligned_target": "T", "aligned_control": "A", "hard_negative": "H", "style_control": "S", "paraphrase_target": "P"}
DIMS = ["address_politeness", "register_formality", "sentence_shape", "orthography_punctuation", "discourse_format"]
VERDICTS = {"PASS", "MINOR", "FAIL"}
TAGS = {
    "H_METRIC_REDESCRIBED", "H_ADDS_PRESSURE", "H_UNSUPPORTED_FACT", "H_STILL_INAPPROPRIATE", "H_NEAR_COPY_OF_T",
    "A_KEEPS_PRESSURE", "A_CHANGES_TASK", "T_WEAK_ELICITATION", "T_FABRICATED_STAKES", "T_BLUNT_COMMAND",
    "P_CHANGES_MECHANISM", "P_NEAR_COPY", "FAMILY_NOT_GROUNDED", "FAMILY_BETTER_FIT_ELSEWHERE",
    "CONTEXT_DEPENDENT_ANCHOR", "TASK_DRIFT_ACROSS_SET", "LANGUAGE_DRIFT", "ROLE_MISLABELED_ANCHOR",
    "S_MANNER_NOT_REPRODUCED", "S_INSUFFICIENT_MANNER", "S_TOPIC_NOT_DISJOINT", "S_RETAINS_MECHANISM_CUE",
    "S_CREATES_PRESSURE", "S_IS_PARAPHRASE", "S_TEMPLATE_VOICE", "S_ADDS_SUBTASK", "S_LANGUAGE_CHANGED", "NONE",
}
REQUIRED = {
    "candidate_id": str, "verdict": str, "tags": list, "reason": str,
    "h_decisive_fact_ok": bool, "family_grounded": bool,
    "s_dimensions_realised": list, "s_dimensions_missing": list,
    "s_topic_disjoint": bool, "s_cue_free": bool, "s_same_speaker": bool,
}
OPTIONAL = {"notable": str, "family": str, "anchor_role": str, "contract_source": str, "human_verify_verdict": str, "human_verify_notes": str}
SCHEMA_VERSION = "harley_set_audit_verdict_v1"


def jl(path: pathlib.Path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_roots(pipeline_version: str | None = "v6"):
    """Finished run roots; by default only those whose final manifest says v6.

    The same candidate_id recurs across pipeline versions (same anchor, rebuilt
    under v3/v5/v6), so an unfiltered search would hit an old root first.
    """
    roots = []
    for p in RUNS_DIR.glob("*/variants/final/approved_contrast_sets.jsonl"):
        root = p.parent.parent.parent
        if pipeline_version:
            try:
                policy = json.load(open(root / "variants" / "final" / "manifest.json")).get("policy") or {}
            except Exception:
                continue
            if policy.get("pipeline_version") != pipeline_version:
                continue
        roots.append(root)
    return sorted(roots)


def find_set(candidate_id: str, run: pathlib.Path | None):
    roots = [run] if run else run_roots()
    if run and not run.is_absolute():
        roots = [RUNS_DIR / run]
    hits = []
    for root in roots:
        for name, status in (("approved_contrast_sets.jsonl", "approved"), ("excluded_contrast_sets.jsonl", "excluded")):
            path = root / "variants" / "final" / name
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if candidate_id in line:
                        row = json.loads(line)
                        if row.get("candidate_id") == candidate_id:
                            hits.append((root, status, row))
    if not hits:
        sys.exit(f"candidate {candidate_id} not found in {[r.name for r in roots]} (v6 run roots only; pass --run for another)")
    if len(hits) > 1:
        sys.exit(f"candidate {candidate_id} is in several run roots {[h[0].name for h in hits]}; pass --run")
    return hits[0]


def prompt_of(role):
    if "user_prompt" in role:
        return role["user_prompt"]
    return "\n".join(m.get("content", "") for m in role.get("rendered_messages") or [] if m.get("role", "user") == "user")


def language_of(root: pathlib.Path, row):
    sha = row.get("source_prompt_sha256")
    for cand in (root, ) + tuple(parent_roots(root)):
        for s in jl(cand / "sampling" / "sampled_turns.jsonl"):
            if s.get("source_prompt_sha256") == sha:
                return s.get("language") or s.get("lang")
    return None


def parent_roots(root: pathlib.Path):
    # style_refresh_v6_waveN -> forward_v1_waveN_v5
    name = root.name
    if "style_refresh_v6_wave" in name:
        n = name.rsplit("wave", 1)[-1]
        return [RUNS_DIR / f"harley_msv1_forward_v1_wave{n}_v5"]
    return []


def sim(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def render(root, status, row, show_pipeline=False):
    if "complete_contrast" not in row:
        return f"## {row.get('candidate_id')}  status={status}\n(no complete_contrast in this row; final_status={row.get('final_status') or row.get('status')})\n" + json.dumps({k: row.get(k) for k in ('final_status', 'status', 'repair_rounds', 'behavior_family', 'anchor_role')}, ensure_ascii=False)
    roles = row["complete_contrast"]["roles"]
    pr = {r: prompt_of(roles[r]) for r in ROLES}
    plan = row.get("plan") or {}
    rc = plan.get("role_contracts") or {}
    hn = rc.get("hard_negative") or {}
    sc = rc.get("style_control") or {}
    con = row.get("construction") or {}
    pairs = {f"{LETTER[x]}-{LETTER[y]}": sim(pr[x], pr[y]) for i, x in enumerate(ROLES) for y in ROLES[i + 1:]}
    sj = (row.get("cue_retention") or {}).get("style_content_word_jaccard_to_target")
    hv = bool(con.get("human_verify_required") or row.get("human_verify_required"))
    out = [
        f"## {row['candidate_id']}  run={root.name} status={status} family={row.get('behavior_family')} anchor={row.get('anchor_role')} "
        f"classified={row.get('classified_anchor_role')} native_h={row.get('native_h')} contract_source={row.get('behavior_contract_source')} "
        f"turn_index={row.get('source_turn_index')} lang={language_of(root, row)} repair_rounds={con.get('repair_rounds')} human_verify={hv}",
        "SIMILARITY(char ratio): " + " ".join(f"{k}={v:.2f}" for k, v in pairs.items()) + f" len_T={len(pr['misaligned_target'])}",
        f"MECHANISM: {row.get('behavior_mechanism')}",
        f"PLAN.decision_target_mode={plan.get('target_mode')}",
        f"PLAN.H.surface_action: {hn.get('surface_action')}",
        f"PLAN.H.original_fact: {hn.get('original_fact_in_target')}",
        f"PLAN.H.decisive_fact: {hn.get('decisive_fact')}",
    ]
    fs = plan.get("family_selection")
    if fs:
        out.append(f"PLAN.family_selection: {json.dumps(fs, ensure_ascii=False)}")
    dt = sc.get("disjoint_task") or {}
    out.append(f"PLAN.S.domain: {json.dumps(sc.get('domain_selection') or {}, ensure_ascii=False)[:600]}")
    out.append(f"PLAN.S.task: {dt.get('task_summary')} | deliverable: {dt.get('required_deliverable')}")
    out.append(f"PLAN.S.disjointness: {dt.get('disjointness_argument')}")
    md = sc.get("manner_dimensions") or {}
    for d in DIMS:
        e = md.get(d) or {}
        out.append(f"PLAN.S.manner_dimensions.{d}: status={e.get('status')} quote_T={json.dumps(e.get('quote'), ensure_ascii=False)} note={e.get('note')}")
    out.append(f"S_JACCARD(content words S vs T): {sj}")
    for r in ROLES:
        out.append(f"\n[{r}]{' (ANCHOR)' if roles[r].get('is_anchor') else ''}\n{pr[r]}")
    if hv:
        hv_rows = [h for h in jl(root / "variants" / "final" / "human_verify.jsonl") if h.get("candidate_id") == row["candidate_id"]]
        out.append("\n### human_verify flags (judge concerns on roles the refresh did not touch; decide them)")
        for h in hv_rows:
            fl = h.get("flags") or {}
            jd = fl.get("judge_decisions") or {}
            out.append(f"- judge decisions: primary={jd.get('primary')} secondary={jd.get('secondary')}; global_checks failed={fl.get('global_checks')}; h_pair_checklist failed={fl.get('h_pair_checklist')}; fixed_contract={fl.get('fixed_contract_failures')}")
            for rr in fl.get("role_reviews") or []:
                out.append(f"- role={rr.get('role')} flagged_by={rr.get('judge')} codes={rr.get('defect_codes')}\n  evidence: {rr.get('evidence')}")
    if show_pipeline:
        adj = con.get("adjudication") or {}
        out.append("\n### pipeline judges (shown on request; do not let this replace your own reading)")
        out.append(json.dumps({"adjudication": adj, "repair_history": con.get("repair_history")}, ensure_ascii=False)[:4000])
    return "\n".join(out)


def validate(v: dict, candidate_id: str):
    errors = []
    for k, t in REQUIRED.items():
        if k not in v:
            errors.append(f"missing {k}")
        elif not isinstance(v[k], t):
            errors.append(f"{k} must be {t.__name__}")
    for k, t in OPTIONAL.items():
        if k in v and v[k] is not None and not isinstance(v[k], t):
            errors.append(f"{k} must be {t.__name__}")
    extra = set(v) - set(REQUIRED) - set(OPTIONAL) - {"schema_version", "reviewer", "recorded_at_utc", "run"}
    if extra:
        errors.append(f"unknown fields {sorted(extra)}")
    if v.get("candidate_id") != candidate_id:
        errors.append("candidate_id mismatch")
    if v.get("verdict") not in VERDICTS:
        errors.append("verdict must be PASS|MINOR|FAIL")
    bad = [t for t in v.get("tags", []) if t not in TAGS]
    if bad:
        errors.append(f"unknown tags {bad}")
    if v.get("verdict") == "PASS" and v.get("tags") not in ([], ["NONE"]):
        errors.append("PASS must carry no tags (or NONE)")
    if v.get("verdict") in {"MINOR", "FAIL"} and (not v.get("tags") or v.get("tags") == ["NONE"]):
        errors.append("MINOR/FAIL must carry at least one tag")
    for k in ("s_dimensions_realised", "s_dimensions_missing"):
        bad = [d for d in v.get(k, []) if d not in DIMS]
        if bad:
            errors.append(f"{k}: unknown dimensions {bad}")
    if len(v.get("reason", "")) < 20:
        errors.append("reason too short; quote the offending phrase or say why it is clean")
    return errors


def verdict_path(root: pathlib.Path, candidate_id: str, reviewer: str):
    d = root / "audit" / "verdicts"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{candidate_id}.{reviewer}.json"


def cmd_render(a):
    root, status, row = find_set(a.candidate_id, resolve_run(a.run) if a.run else None)
    print(render(root, status, row, show_pipeline=a.show_pipeline))


def cmd_record(a):
    root, status, row = find_set(a.candidate_id, resolve_run(a.run) if a.run else None)
    raw = sys.stdin.read() if a.verdict_json == "-" else pathlib.Path(a.verdict_json).read_text(encoding="utf-8")
    v = json.loads(raw)
    errs = validate(v, a.candidate_id)
    if errs:
        sys.exit("verdict rejected:\n  " + "\n  ".join(errs))
    v.setdefault("family", row.get("behavior_family"))
    v.setdefault("anchor_role", row.get("anchor_role"))
    v.setdefault("contract_source", row.get("behavior_contract_source"))
    v["schema_version"] = SCHEMA_VERSION
    v["reviewer"] = a.reviewer
    v["run"] = root.name
    v["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
    p = verdict_path(root, a.candidate_id, a.reviewer)
    existed = p.exists()
    p.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'updated' if existed else 'recorded'} {p}")


def ordered_ids(root: pathlib.Path):
    rows = jl(root / "variants" / "final" / "approved_contrast_sets.jsonl")
    rows.sort(key=lambda r: (r.get("behavior_family") or "", r["candidate_id"]))
    return rows


def resolve_run(run: str) -> pathlib.Path:
    p = pathlib.Path(run)
    return p if p.is_absolute() else RUNS_DIR / run


def cmd_next(a):
    root = resolve_run(a.run)
    done = {p.name.split(".")[0] for p in (root / "audit" / "verdicts").glob(f"*.{a.reviewer}.json")}
    out = []
    for r in ordered_ids(root):
        if r["candidate_id"] in done:
            continue
        if a.family and r.get("behavior_family") != a.family:
            continue
        if a.human_verify_only and not ((r.get("construction") or {}).get("human_verify_required") or r.get("human_verify_required")):
            continue
        out.append(r["candidate_id"])
        if len(out) >= a.n:
            break
    total = len(ordered_ids(root))
    print("\n".join(out) if out else "(none left)")
    print(f"# {len(done)}/{total} reviewed by {a.reviewer} in {root.name}", file=sys.stderr)


def cmd_status(a):
    root = resolve_run(a.run)
    files = sorted((root / "audit" / "verdicts").glob("*.json")) if (root / "audit" / "verdicts").exists() else []
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    if a.reviewer:
        rows = [r for r in rows if r.get("reviewer") == a.reviewer]
    total = len(ordered_ids(root))
    by = {}
    for r in rows:
        by.setdefault(r["reviewer"], {"PASS": 0, "MINOR": 0, "FAIL": 0})
        by[r["reviewer"]][r["verdict"]] += 1
    print(json.dumps({"run": root.name, "approved_sets": total, "verdicts_by_reviewer": by}, indent=1))
    if a.csv:
        cols = ["candidate_id", "run", "reviewer", "family", "anchor_role", "contract_source", "verdict", "tags", "h_decisive_fact_ok",
                "family_grounded", "s_dimensions_realised", "s_dimensions_missing", "s_topic_disjoint", "s_cue_free", "s_same_speaker",
                "human_verify_verdict", "human_verify_notes", "notable", "reason", "recorded_at_utc"]
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                r = dict(r)
                for k in ("tags", "s_dimensions_realised", "s_dimensions_missing"):
                    r[k] = "|".join(r.get(k) or [])
                w.writerow(r)
        print(f"wrote {a.csv} ({len(rows)} rows)")


def cmd_rubric(a):
    for p in RUBRIC_CANDIDATES:
        if p.exists():
            print(p)
            return
    sys.exit("rubric_v6.md not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render"); p.add_argument("candidate_id"); p.add_argument("--run"); p.add_argument("--show-pipeline", action="store_true"); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("record"); p.add_argument("candidate_id"); p.add_argument("--run"); p.add_argument("--reviewer", required=True); p.add_argument("--verdict-json", required=True); p.set_defaults(fn=cmd_record)
    p = sub.add_parser("next"); p.add_argument("--run", required=True); p.add_argument("--reviewer", required=True); p.add_argument("--human-verify-only", action="store_true"); p.add_argument("--family"); p.add_argument("--n", type=int, default=1); p.set_defaults(fn=cmd_next)
    p = sub.add_parser("status"); p.add_argument("--run", required=True); p.add_argument("--reviewer"); p.add_argument("--csv"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("rubric"); p.set_defaults(fn=cmd_rubric)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
