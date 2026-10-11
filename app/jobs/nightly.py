"""Nightly batch job — the precomputation heart of the product.

Roadmap principle: "precompute at night rather than compute on request".
The API only READS signals; this job is the only writer.

Planned pipeline (phase 1):
    1. fetch    — download new EDGAR data (bulk companyfacts/submissions
                  ZIPs + incremental 8-K, Form 4) via app.edgar.client
    2. normalize — map heterogeneous XBRL tags to standard indicators
                  (app/normalize/, driven by xbrl_map.yaml)
    3. signals  — run app/signals/* calculators and event detectors,
                  store each result with date + source filing (traceability)

Invocation (from the repo root, so that `app` is importable):
    uv run python -m app.jobs.nightly
The `-m` flag matters: it puts the current directory on sys.path; running
`python app/jobs/nightly.py` directly would fail to import `app.*`.

Scheduling: manual during dev; `cron` on the VPS in production
(scheduler choice per roadmap §4 — cron first, RQ/Celery only in phase 2+).
"""


def main():
    # TODO(phase 1): replace with the fetch -> normalize -> signals pipeline.
    print("nightly: fetch -> normalize -> signals (TODO phase 1)")


if __name__ == "__main__":
    # Enables `python -m app.jobs.nightly`; guards against main() running
    # when this file is merely imported by another module or a test.
    main()
