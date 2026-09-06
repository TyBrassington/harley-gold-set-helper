# HARLEY gold-set helper

Tooling for independently auditing HARLEY v6 WildChat behaviour-contrast sets
(five roles: misaligned target T, aligned control A, hard negative H, style
control S, paraphrase target P). Reviewers step through a run root one set at a
time, and each verdict is written as one JSON file the review app can read.

## Layout

| Path | What |
|---|---|
| `claude/audit-contrast-set/` | Skill for Claude Code. Install into `~/.claude/skills/`. |
| `codex/audit-contrast-set/` | Same skill for Codex CLI. Install into `~/.codex/skills/`. Differs from the Claude copy only in one phrase of the `SKILL.md` description. |
| `kit/` | Batch alternative: `audit_prep_v6.py` renders a run root into 24-set slices, `slice_auditor_prompt_v6.md` is the per-slice wrapper. See `kit/README.md`. |
| `install.sh` | Copies the skill into one or both skill directories. |

Each skill directory holds three files:

- `SKILL.md`: the procedure the reviewing agent follows (read rubric once, render, judge, record, print next id).
- `rubric_v6.md`: the audit rubric. T/A/H/P definitions and tags match the Sep 3 v5 audit; S is the v6 definition (T's manner reproduced on a disjoint task along five declared dimensions).
- `audit_set.py`: helper with subcommands `rubric`, `render`, `record`, `next`, `status`. Standard library only.

## Install

```bash
git clone git@github.com:TyBrassington/harley-gold-set-helper.git
cd harley-gold-set-helper
./install.sh            # or: ./install.sh claude   /   ./install.sh codex
```

Then in Claude Code or Codex: `/audit-contrast-set wildchat_03c3f36c981b387b`, or ask
for "the next set in harley_msv1_forward_v1_wave4_v6".

## Paste mode (no lab access)

The review app's copy button emits one JSON record per set (`candidate_id`,
`prompts.T/A/H/S/P`, `H_plan`, `S_declared_realised_dimensions`, ...). A human
reviewer pastes it into Claude Code or Codex while verifying the set by hand.
With the skill installed, the agent reads the bundled `rubric_v6.md`, judges
from the pasted prompts, and replies with the verdict JSON, per-role findings,
and a final `DECISION:` line (gold, gold with a family relabel, or reject). It does not run `render`, `record`, or `next`, and nothing is written.
The human enters the decision in the app.

## Where the data lives

The helper reads finished v6 run roots (`variants/final/approved_contrast_sets.jsonl`,
`excluded_contrast_sets.jsonl`, `human_verify.jsonl`) and writes verdicts to
`<run_root>/audit/verdicts/<candidate_id>.<reviewer>.json`. The default runs
directory is the lab share checkout:

```
/local-scratch/localhome/wgb/behavior-latent-library/wildchat_candidate_mining_2/runs
```

Set `HARLEY_RUNS_DIR` if the run roots are somewhere else. Only run roots whose
`variants/final/manifest.json` declares `pipeline_version: v6` are searched.

## Verdict file

Schema `harley_set_audit_verdict_v1`. Required fields: `candidate_id`, `verdict`
(`PASS|MINOR|FAIL`), `tags` (closed list in the rubric; empty iff PASS), `reason`,
`h_decisive_fact_ok`, `family_grounded`, `s_dimensions_realised`,
`s_dimensions_missing`, `s_topic_disjoint`, `s_cue_free`, `s_same_speaker`,
`decision` (`gold` for PASS/MINOR, `reject` for FAIL).
Optional: `notable`, `family`, `anchor_role`, `contract_source`,
`human_verify_verdict`, `human_verify_notes`, `family_override` (required with
the FAMILY_BETTER_FIT_ELSEWHERE tag: the better-fitting family; the set stays
gold and the reviewer changes the behaviour in the app).

`python audit_set.py status --run RUN --csv out.csv` flattens all verdicts for a run.
