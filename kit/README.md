# Audit kit for v6 contrast sets

Everything an independent auditor (Astra, Fable, or a human) needs to score v6
sets the same way the Sep 3 v5 wave-1 audit scored v5 sets.

| File | What |
|---|---|
| `rubric_v6.md` | The rubric the auditor reads first. Same T/A/H/P definitions, tags, verdicts and output shape as the v5 rubric (`../harley_msv1_forward_v1_wave1_v5/audit/rubric_v5_20260903.md`); the style_control section is the v6 manner-on-a-disjoint-task definition, the S tags are new, and the output row gains five S fields. |
| `slice_auditor_prompt_v6.md` | Per-slice wrapper. Fill `{RUBRIC_PATH}`, `{SLICE_PATH}`, `{OUT_PATH}`, `{N}`. |
| `audit_prep_v6.py` | Renders a run root into `sets.md`, `pairs.tsv`, `funnel.json` and `slices/slice_N.md` (24 sets each). |

## Run

```bash
cd /local-scratch/localhome/wgb/behavior-latent-library/wildchat_candidate_mining_2/runs
PY=/localhome/wgb/.venvs/bll-mining/bin/python
$PY audit_kit_v6/audit_prep_v6.py harley_msv1_forward_v1_wave4_v6 harley_msv1_forward_v1_wave4_v6/audit/prep_v6
$PY audit_kit_v6/audit_prep_v6.py harley_msv1_style_refresh_v6_wave1 harley_msv1_style_refresh_v6_wave1/audit/prep_v6 --parent harley_msv1_forward_v1_wave1_v5
$PY audit_kit_v6/audit_prep_v6.py harley_msv1_style_refresh_v6_wave2 harley_msv1_style_refresh_v6_wave2/audit/prep_v6 --parent harley_msv1_forward_v1_wave2_v5
$PY audit_kit_v6/audit_prep_v6.py harley_msv1_style_refresh_v6_wave3 harley_msv1_style_refresh_v6_wave3/audit/prep_v6 --parent harley_msv1_forward_v1_wave3_v5
```

Refresh run roots have no `sampling/`, so pass the v5 parent with `--parent` to fill the `lang=` field.

Then, for each `slices/slice_N.md`, send one auditor the wrapper with the four
placeholders filled and collect `verdicts_N.jsonl`. Merge, then a calibration
pass over disagreements and over every set tagged FAIL. Final CSV goes to
`<run_root>/audit/verdicts_v6_<date>.csv`.

## Comparability with the v5 audit

Keep the T/A/H/P tags and PASS/MINOR/FAIL semantics unchanged so keep rates are
comparable with 135/30/20 on v5 wave 1. Only the S column moved: a v5 set could
be tagged `S_DIFFERENT_TASK`; a v6 set is *required* to be a different task and
is tagged on manner, disjointness, cue leakage, or template voice instead.

## What the slice shows for S

`PLAN.S.manner_dimensions.<dim>` gives the planner's status (`realised` or
`not_applicable`), the quote from T it relied on, and its note. The auditor
verifies each realised dimension in the rendered S and records what was actually
found in `s_dimensions_realised` / `s_dimensions_missing`. `S_JACCARD` is the
content-word overlap between S and T (0.0 is fully disjoint); it is diagnostic
only.
