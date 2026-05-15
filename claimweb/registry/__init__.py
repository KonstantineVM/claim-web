"""claimweb.registry — unmapped entity registry for human review.

Fetchers write unknown entities (no canonical CLAIM-WEB node ID) to
claimweb/registry/unmapped/{source_id}_{period}.json.  These files are
runtime-generated and gitignored; they accumulate across sessions and
require periodic human review to promote to the canonical registry.
"""
