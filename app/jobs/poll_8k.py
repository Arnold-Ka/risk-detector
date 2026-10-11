"""Incremental poll job for hot filings — 8-K events and Form 4 insider
transactions, run every 10 minutes (roadmap §4 component 1), unlike the
nightly bulk job.

Why separate: 8-K/Form 4 drive *timely* alerts (paid tier promises
"within 15 minutes"), so they cannot wait for the nightly run.

TODO(phase 1): poll data.sec.gov submissions feed for new filings of
watched companies, parse 8-K items (1.03, 2.04, 4.01, 4.02, 5.02) and
Form 4 XML, then write rows into `filings` + `signals`.
"""
