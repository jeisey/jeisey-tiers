"""Insights: deterministic weekly fantasy stories over the build's published evidence (ADR-116).

The boards answer "what is he worth" and the Opportunity Board "what are managers doing about
him". Insights answers the questions a manager asks between them — *is my disappointing
starter still getting the ball, who has a real route to a big week at low roster share, whose
role opened up, whose streak is backed by usage* — and presents each answer as a
self-contained story with its evidence, a counterpoint and its caveat.

The design is the separation (ADR-116):

* **Downstream only.** It reads published records (usage, season actuals, recent form,
  weekly projections and context, ESPN readings, the Opportunity Board's roster codes) and the
  in-memory nflverse frames the same build already holds. Nothing reads it back: no model,
  value, rank, tier, Pick of the Week or decision tool.
* **Rules, not search.** Each family has fixed calendar windows, explicit qualification
  predicates, minimum samples, an effect threshold, an ordering and tie-breakers
  (:mod:`ffdraft.insights.rules`). No split is searched for an impressive headline.
* **Words from numbers.** Text is a template over structured evidence
  (:mod:`ffdraft.insights.text`); the validator checks every printed number against it.
"""

from ffdraft.insights.build import InsightsResult, build_insights
from ffdraft.insights.rules import INSIGHT_RULE, INSIGHTS_RULE_VERSION, SELECTION_RULE

__all__ = [
    "INSIGHTS_RULE_VERSION",
    "INSIGHT_RULE",
    "SELECTION_RULE",
    "InsightsResult",
    "build_insights",
]
