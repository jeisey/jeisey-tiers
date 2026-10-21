/**
 * "Reading the boards" — the Data tab's home for what each board's columns, bars and rules mean
 * (ADR-115).
 *
 * Each board used to explain itself in captions and paragraphs above and below its table, and
 * the same methodology was repeated on four boards and in the player card. Those passages live
 * here now, grouped by board, so the boards lead with players, values and controls and a reader
 * who wants the method finds all of it in one place. A board keeps only what its own screen
 * needs to be read — units, time horizons, attribution and state (a stale feed, a bound, a
 * disabled filter). Loaded lazily with the Data tab's other long reading, so no board pays for it.
 */

import type { ReactNode } from "react";

interface Entry {
  readonly term: string;
  readonly body: ReactNode;
}

interface Group {
  readonly id: string;
  readonly title: string;
  readonly entries: readonly Entry[];
}

const GROUPS: readonly Group[] = [
  {
    id: "guide-ros",
    title: "ROS board",
    entries: [
      {
        term: "Rest-of-season columns",
        body:
          "Every ROS column is a rest-of-season quantity computed at the cutoff week the board names — none of them is the preseason value of the same name. It is what is left of the season from another model, over another horizon, with another replacement baseline.",
      },
      {
        term: "ROS rank",
        body:
          "The model's published order, and not adjusted for injuries. Sorting the table re-orders rows without changing it, positional ranks sort within each position, and a player the availability policy holds back leaves his rank unused rather than renumbering anyone.",
      },
      {
        term: "Tier bands",
        body:
          "Rest-of-season tiers are bands, not lines. Membership reproduces across resamples; the exact cut positions do not, so read a player near an edge as belonging to both.",
      },
      {
        term: "Bars",
        body:
          "The P25–P75 bar and its median tick share one scale across the board. In the table, interval and uncertainty bars are scaled against the widest on the rows shown.",
      },
      {
        term: "Rank lane",
        body:
          "Two positional ranks on a log scale with 1 at the left: the square is the rest-of-season rank and the triangle the season-to-date rank by points. Each player is ranked within his own position — QB4 and RB4 are separate standings.",
      },
      {
        term: "The mark beside a name",
        body:
          "The availability reading — roster code, injury designation, or a reviewed season-ending report. It decides what is actionable and is no input to any number.",
      },
      {
        term: "Hide bye-week players",
        body:
          "Hides players whose team has no game in the build's target week (the week after its cutoff), by the build's own schedule. A team whose game that week is already over is not on a bye. A missing projection, a pending betting line, an injury or an unknown team never counts as a bye, and a player whose schedule is unknown stays visible. The filter never renumbers a rank; a search does not override it.",
      },
    ],
  },
  {
    id: "guide-season",
    title: "Season to date",
    entries: [
      {
        term: "Szn rank, Total pts, Avg pts/g",
        body:
          "Actual results through the cutoff week in the selected scoring, not projections. Szn rank orders every player at the position who has appeared by points scored (ties share a rank), whichever board lists him; Avg pts/g counts only games he appeared in. A dash means no appearances or no data.",
      },
      {
        term: "RoS vs Szn",
        body:
          "Szn rank minus RoS rank, in places: +7 means the rest-of-season model ranks him 7 places higher than his production so far, −7 lower.",
      },
    ],
  },
  {
    id: "guide-opportunity",
    title: "Opportunity Board",
    entries: [
      {
        term: "Four readings, never combined",
        body:
          "Rest-of-season value (the model, copied unchanged from the ROS board); role (observed: the position's leading measure — pass attempts for a quarterback, snap share otherwise — latest game against the average of earlier games); add momentum (the published slope of the add count over the retained window, with its span); and the next game (sportsbook context no model reads; nothing rates an opponent). A filter tests one of them at a time.",
      },
      {
        term: "Surfaced rows",
        body:
          "A row marked surfaced is published because current evidence made him relevant from beyond the tier depth. He carries the model's rest-of-season value and no tier.",
      },
      {
        term: "Bars",
        body:
          "Add and drop bars are scaled against the largest count on the rows shown; the value bar against the largest rest-of-season value.",
      },
      {
        term: "Recent",
        body:
          "The positional rank by total points in the selected recent weeks, among every player at the position who appeared in those weeks, with points per game and games under it. vs Szn is Szn rank minus Recent rank in places, positive when the recent rank is better. The badge on a name is a descriptive breakout category, with its evidence one tap away.",
      },
      {
        term: "ESPN rost",
        body:
          "The share of ESPN leagues rostering him, with its change in percentage points over about 7 days and 1 day and ESPN's start share: ESPN's population, not your league, and popularity rather than a projection.",
      },
    ],
  },
  {
    id: "guide-sleeper",
    title: "Sleeper adds and drops",
    entries: [
      {
        term: "What a count is",
        body:
          "The number of Sleeper rosters that added (or dropped) the player inside the requested window, as Sleeper reported it. A count of transactions: never a price, never a rank, and never subtracted from one. Sleeper publishes no observation time, so the time shown is when the snapshot was retrieved.",
      },
      {
        term: "Top 100 only",
        body:
          "Sleeper's trending feeds return the 100 most-added and, separately, the 100 most-dropped players, whatever is requested (measured 2026-10-21: limits up to 5,000, every window from 1 to 168 hours, and every pagination parameter tried returned the same 100). A player outside a list has an unknown count — at most that list's smallest count — never zero. Most players are in neither list, and many are in only one.",
      },
      {
        term: "Net adds",
        body:
          "Adds minus drops, exact only when both counts were observed. When only his adds were in the list, the net is shown as a bound — “≥ +531,586” means at least that, because his drops were below the drop list's smallest count — and sorts by that bound. With neither count, there is no net.",
      },
      {
        term: "Add momentum",
        body:
          "The slope of his observed add counts over the retained window, always printed with the span it was measured over. A day he was outside the add list is a gap, never a zero; the net slope uses only days with both counts.",
      },
      {
        term: "No Sleeper id",
        body:
          "A player with no verified Sleeper id — or one two players claim — cannot be matched to either list, and his counts read as unknown.",
      },
    ],
  },
  {
    id: "guide-startsit",
    title: "Start/Sit",
    entries: [
      {
        term: "The comparison",
        body:
          "Up to four players for one slot. Each is a distribution of his points for the target week given that he plays, from the weekly start/sit model; the pick is whoever gives you the best chance to win the week at your margin.",
      },
      {
        term: "Range bar",
        body:
          "Whisker P10–P90, box P25–P75, tick the median; the dashed line is a startable week at his position in your league.",
      },
      {
        term: "Opp. allows, vs typical",
        body:
          "Opp. allows ranks his opponent by fantasy points allowed to the position this season, shrunk toward the league rate; 1st is the most generous. “vs typical” is the median against the player's typical week, with the input that moved it most.",
      },
      {
        term: "Week rank and sorting",
        body:
          "Week rank orders this week's medians within his position; RoS rank is his rest-of-season positional rank in your league. A column heading sorts the whole board (P10–P90 by the width of the range); blanks sort last either way, and an “Order by” choice restores the board's own order.",
      },
    ],
  },
  {
    id: "guide-potw",
    title: "Pick of the Week",
    entries: [
      {
        term: "How a pick is chosen",
        body:
          "A player is eligible when Sleeper reports him added at least as often as the median of his own position's non-zero add counts on the board, with provably more adds than drops over the same window (a bound counts only when it proves it), no long absence, and no roster code that says he cannot play. Among the eligible, the pick is the one the rest-of-season model values highest — the add count decides membership and never the ordering, because a count of transactions and a number of points share no unit and may not be combined into a score.",
      },
      {
        term: "No rostered percentage",
        body:
          "Pick of the Week does not use a rostered percentage. ESPN's rostered share on the Opportunity Board and the card describes ESPN leagues, not yours. An add count is availability evidence in the direction that matters — a roster that added a player did not have him — and it is shown as a count, never as a percentage.",
      },
    ],
  },
  {
    id: "guide-trade",
    title: "Trade",
    entries: [
      {
        term: "Floor and ceiling",
        body:
          "The 10th and 90th percentiles of a player's total value over the remaining weeks — not weekly consistency, and not one game's upside.",
      },
      {
        term: "Who is not a target",
        body:
          "Availability and absence never change a value; they keep a player from leading suggestions on an estimate that does not read injury news. A player listed Out, Doubtful or Questionable for this week only is still a target, with the warning beside his name; players on a reserve list or absent three weeks or more are included only with “Include players expected back”, and a season that is over never is.",
      },
    ],
  },
  {
    id: "guide-card",
    title: "Player card",
    entries: [
      {
        term: "Role, week by week",
        body:
          "Each reading is his latest game against the average of his earlier games. Shares are drawn on a 0–100% scale; attempts and points against his own peak. On the drive row, each bar is the share of drives he got the ball on, and the notch is where the same number would land if spread at random: short of it, bunched into fewer drives; above it, spread across more. Descriptive, not a forecast.",
      },
      {
        term: "Roster moves",
        body:
          "Drops left of centre, adds right, on the Opportunity Board's own axis — the 85th percentile of its non-zero counts; a chevron marks a count past it, and the numbers beneath are the reading.",
      },
    ],
  },
  {
    id: "guide-draft",
    title: "Draft boards",
    entries: [
      {
        term: "Tier table",
        body:
          "Fair rank is the published order; sorting re-orders the rows without changing it. Interval and uncertainty bars are scaled against the widest on the rows shown — a long amber bar means the projection is thin, not that the player is bad.",
      },
      {
        term: "Arbitrage table",
        body:
          "The model's fair rank compared with the selected ADP market, as arithmetic. Columns appear only for the markets the build published, and the bar is the signed difference in picks — not points, not dollars and not a probability. Confidence describes how much draft evidence stands behind the price, not how likely the player is to be a bargain.",
      },
    ],
  },
];

export function BoardGuide(): React.JSX.Element {
  return (
    <div className="board-guide">
      {GROUPS.map((group) => (
        <section key={group.id} className="board-guide-group" aria-labelledby={group.id}>
          <h3 id={group.id} className="board-guide-title">
            {group.title}
          </h3>
          <dl className="definition-grid">
            {group.entries.map((entry) => (
              <div key={entry.term}>
                <dt>{entry.term}</dt>
                <dd>{entry.body}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

export default BoardGuide;
