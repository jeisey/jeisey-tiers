"""The in-season signal layer: what a player is doing now, published beside the model.

The rest-of-season model answers one question — what is he worth from here — and the
Opportunity Board answers a second — what are managers doing about him. Neither says what a
waiver decision usually turns on: whether his **role** is changing, what the **workload**
looks like week by week, whether his scoring leans on touchdowns, and who he plays next.

This package publishes those facts as two artifacts, and the separation from the model is
the design (ADR-091):

* :mod:`ffdraft.signals.usage` — observed role and production, week by week, from the
  nflverse weekly rows and snap counts every in-season build already downloads;
* :mod:`ffdraft.signals.matchup` — each team's next unplayed game, including sportsbook
  lines as **published context only**.

Nothing here is a model input and nothing here reads a model output. No function in this
package can move a projection, a VORP, a rank, a tier, a Pick of the Week selection, or an
add count; the signals sit beside those numbers on a card and never inside them.
"""

from ffdraft.signals.matchup import (
    MATCHUP_RULE_VERSION,
    SPORTSBOOK_CONTEXT_STATEMENT,
    build_team_matchup_records,
)
from ffdraft.signals.usage import (
    EXPECTED_POINTS_STATEMENT,
    ROLE_CHANGE_METRICS,
    USAGE_RULE,
    USAGE_RULE_VERSION,
    UsageRule,
    build_player_usage_records,
    current_teams_from_roster,
)

__all__ = [
    "EXPECTED_POINTS_STATEMENT",
    "MATCHUP_RULE_VERSION",
    "ROLE_CHANGE_METRICS",
    "SPORTSBOOK_CONTEXT_STATEMENT",
    "USAGE_RULE",
    "USAGE_RULE_VERSION",
    "UsageRule",
    "build_player_usage_records",
    "build_team_matchup_records",
    "current_teams_from_roster",
]
