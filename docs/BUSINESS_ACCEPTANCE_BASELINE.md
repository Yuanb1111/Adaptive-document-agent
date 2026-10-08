# Business acceptance baseline: 9c837be

The first six-file pilot failed its scoped business gate. All six public-source
documents completed analysis and produced PowerPoint; successful generation did
not imply factual completeness or correctness.

The source-first checklist was locked before generation. It contained 48 minimum
fact groups. The scoped review found 23 erroneous groups and 38 material omission
groups without a specific disclosure of their decision impact. These are group
counts, not counts of independent numeric errors: one group may contain several
incorrect checks and may also omit a condition. They are not population accuracy
estimates. All 128 rendered/native PPT pages were inspected. Full source and
additional-output-claim reviews remain incomplete.

## Frozen run

- Engine: `9c837be116cbf64e0cc59eaa61d5cf9a883fda1f` / pipeline v88.
- Model: DeepSeek `deepseek-flash`, temperature 0, cloud mode, no stage overrides.
- Discovery: 4 workers, 12,000-token chunks; semantic batches of 96.
- Discovery thinking disabled; simple-task reasoning reduced; timeout 120 seconds.
- Automatic focus/routing, model cache disabled, one complete invocation per file.
- Attempt 1 encountered invalid credentials and was retained as a configuration
  failure. Attempt 2 ran once per file after the user updated the credentials.
- Ordinary bounded transport/format/semantic recovery remained enabled. Recorded
  model calls include retries; no inference about provider billing is made.
- Local PowerPoint QA used ArtifactRenderer. LibreOffice/PowerPoint parity has not
  been established by this local pilot.

| Anonymous sample | End-to-end elapsed minutes | Recorded model calls | Incorrect groups | Material omissions | Scoped gate |
|---|---:|---:|---:|---:|---|
| A | 33.6 | 45 | 5 | 7 | Failed |
| B | 16.1 | 32 | 4 | 6 | Failed |
| C | 16.1 | 38 | 8 | 7 | Failed |
| D | 12.8 | 31 | 3 | 6 | Failed |
| E | 15.8 | 29 | 2 | 5 | Failed |
| F | 5.9 | 31 | 1 | 7 | Failed |

The ignored local `output/business_acceptance_9c837be/` folder holds the actual
filled HTML/JSON/CSV report, official-source URLs, source and checklist hashes,
page-level review locators, exact reviewed analysis/PPT hashes, retained attempts,
chapter navigation and measured operation records. Source filenames, source text,
attachments and credentials are excluded from Git.

## Findings guiding the next implementation

1. Source routing can miss the core financial/cash sections while producing an
   apparently complete report of incidental operating measures. Checks confined
   to extracted series cannot discover that failure.
2. Other files already selected the relevant source pages, but downstream unit,
   period, explanation and condition integrity failed. Selecting more pages alone
   will not fix these errors.
3. Bare currency column headers and separate scale declarations can override or
   inherit the wrong scale. Explicit flow periods can become closing dates.
4. Material explanations, latest-period evidence, risks and qualification details
   are often absent. A generic source-conflict disclaimer does not identify the
   actual missing content or its decision impact.
5. The former coverage review used up to 10 recorded calls for one file, consuming
   approximately 22.4 minutes in summed request latency, yet remained unresolved.
   Output and request bounds must accompany input-size bounds.
6. Contents remained on one page in all six exports. Sparse continuation pages,
   long inherited metric headings and internal diagnostic terms still reduced
   readability in some decks.

## Next-version boundary

v89 records physical source sections and selection reasons before extraction,
offers at most one scope-selection request and two complete source checks
(six supplementary pages, 2,048 output tokens per request), and retains bounded
search failures separately from source non-disclosure. It binds retained evidence
and planned themes to actual renderer page scopes in PPT notes/JSON, without
claiming every fact was displayed or semantically reviewed.

The extracted-series coverage review has a three-call limit per review invocation
and an 8,192-token output limit per call. Invalid/incomplete merges roll back and
report the remaining unchecked series. Transport retry limits still apply.

Local finalization provides content locks, topic ordering and one-topic rewriting
over existing evidence. A rewrite uses one bounded structured gateway request,
shows a proposed diff and evidence, and checks the full plan/claim dependencies.
The analytical facts, charts, briefing and other topics remain stable; export
cannot silently repair an approved draft. This does not repair an already
incorrect analytical fact base or certify business acceptance.

Unit fixes have been replayed locally on retained source tables with zero model
calls. The v89 engine has not yet rerun the six-file cloud cohort. The previous
authorization allowed one full invocation per file, so a new paid regression run
requires a new bounded authorization. These six files now become regression
samples; future independent acceptance must retain unseen files.

The reviewer was Codex, not an independent human. Actual human editing time has
not been measured. The pilot covers multiple sectors but only English documents
of one genre. It does not establish general reliability across document types.
