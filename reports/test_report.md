# Test report

Command: `python -m pytest tests/test_research_pipeline.py -q`

Latest run: **9 passed**. Coverage includes timestamp coalescing, elapsed event masks and latency, gap-aware monitoring hours, alarm episode merge behavior, rail episode elapsed duration, moving-mean equation edge cases, deterministic random-seed simulation, gate rail/contact/flatline checks, and insufficient event data.

These are focused unit tests for revised primitives. They do not establish firmware equivalence, validate held-out day isolation in the legacy benchmark, or constitute a complete integration test of all requested deliverables.
