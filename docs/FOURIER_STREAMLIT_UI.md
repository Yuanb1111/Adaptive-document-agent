# FOURIER Streamlit interface

This interface runs through the existing `streamlit run app.py` entry point.
It does not require Sites, a JavaScript build, a database, or an additional
service. Streamlit theme settings live alongside the existing production
watcher settings in `.streamlit/config.toml`.

## User flow

1. Configure the model and session-only API key in the sidebar. Data routing
   remains visible in the Document privacy area.
2. Enter an optional analysis focus, optionally enable page-scope review,
   and upload one PDF. Automatic analysis and explicit retry behavior remain
   unchanged. Changing the focus/model after upload changes the analysis scope.
3. Follow the existing completion events. 100% is shown only after a verified
   PowerPoint payload is returned. An export failure keeps the PPT unavailable.
4. Download PowerPoint from the primary result card. Other report/data formats,
   export diagnostics, and rebuild actions remain available in expanders.
5. Explore the original result tabs. The overview additionally shows available
   document summaries, reporting periods, and the first three findings in report
   order. Sources retain the original text and provenance metadata.

The homepage cover is explicitly illustrative. It is not a preview of a
generated deck, and there are no invented company metrics or sample results in
the product. Presentation content continues to be selected from the actual PDF.

## Brand and implementation

- White and `#F6F7F7` surfaces, black text, and `#7A24FD` primary actions.
- Original combined logo paths from the supplied VI; see `ui/assets/README.md`.
- Web charts reuse `services/fourier_brand.py` colors. Evidence and values are
  unchanged. Existing PPT category color mappings are preserved.
- Roboto / Source Han Sans CN font stacks with system fallbacks. No external
  font, image, or stylesheet requests are introduced.
- Custom HTML is limited to presentational cards; dynamic source strings are
  escaped. Uploads, controls, status, tabs, and downloads remain native widgets.
- CSS uses semantic roles and Streamlit `data-testid` selectors rather than
  generated class names. Recheck styling when upgrading Streamlit.

## Elapsed time

`Current stage` measures the current major workflow phase, using identities in
`ui/processing_stages.py`. Page batches, parallel completions, scoring counters,
translation retries and informational status copy update the visible message
without restarting that phase clock. A genuine phase change starts a new phase
timer; an explicit new analysis attempt resets both clocks. Unknown status text
inherits the current phase; new workflow callers may supply an explicit
`stage_id` to `ProcessingProgress.update`.

The browser retains one monotonic clock anchor per mounted attempt instead of
rebasing it on each server poll. Superseded timer callbacks and stale phase or
attempt snapshots cannot overwrite the current timer. Completion and failure
freeze the values, preserving the last displayed second across delivery jitter.
Component keys and reserved height remain stable to avoid scroll flicker.
These timers do not advance the progress percentage or issue model requests.

## Deployment

Merge the reviewed change into the branch configured in Streamlit Community
Cloud, then allow the app to redeploy. Reboot the app if it retains the old
theme; production source watching intentionally remains disabled. No additional
secrets or dependency changes are needed for this interface.
