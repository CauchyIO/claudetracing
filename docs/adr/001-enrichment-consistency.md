# ADR-001: Enrichment Configuration Consistency Across Team Members

## Status

Proposed

## Context

When multiple team members work on the same project and register to the same MLflow experiment, their enrichment configurations are stored locally in each user's `.claude/settings.json`. This creates a potential inconsistency problem:

- Colleague A enables enrichments: `git`, `files`
- Colleague B enables no enrichments
- Both write traces to the same experiment

Result: The experiment contains traces with inconsistent metadata - some have git commit info, some don't. This makes analysis unreliable and can cause confusion when querying traces.

### The Core Question

When joining an existing experiment, should we infer and enforce the enrichment configuration that others are using?

## Options Considered

### Option A: Infer from Existing Traces

Query recent traces from the experiment and detect which enrichment tags are present.

```python
traces = client.search_traces(experiment_id, max_results=10)
detected = infer_enrichments_from_tags(traces)
# Compare with local config, warn or auto-configure
```

**Pros:**
- Works retroactively on existing experiments
- No schema changes needed
- Self-healing: adapts to what's actually in use

**Cons:**
- Inference can be unreliable (what if first N traces were from a misconfigured user?)
- Performance overhead on every init
- Doesn't express intent, only observed state

### Option B: Store Enrichment Config in Experiment Tags

Set experiment-level metadata when first configured:

```python
client.set_experiment_tag(experiment_id, "claudetracing.enrichments", "git,files,tokens")
```

When joining, read this tag and configure accordingly.

**Pros:**
- Explicit contract: experiment declares expected enrichments
- Single source of truth
- Fast to read (one API call)

**Cons:**
- Requires MLflow experiment write access to set initial tag
- Doesn't help with pre-existing experiments
- Someone must be "first" to define the standard

### Option C: Warn on Mismatch (Advisory Only)

During `traces init` or session start, check if local config differs from experiment patterns and warn the user. Don't enforce, just inform.

**Pros:**
- Non-breaking: existing workflows continue
- Respects user autonomy
- Easy to implement

**Cons:**
- Warnings can be ignored
- Doesn't prevent the inconsistency, only surfaces it
- Relies on users taking action

## Decision

**[PENDING - To be filled after decision]**

## Consequences

**[PENDING - To be filled after decision]**

---

## References

- Related discussion: Enrichment system design
- Implementation: `src/claudetracing/enrichments.py`
