/**
 * "How it works": the models, one board at a time, in plain English.
 *
 * Written for a reader who has never met a quantile. Each board answers one question a
 * fantasy manager would ask, says how the model goes about it in two or three steps, and
 * says what it is and is not allowed to read. It is a reading aid on the Data page and
 * nothing else: no other view imports it.
 *
 * **No metric is typed in here**, for the same reason the rest of the Data page has none
 * (AGENTS.md section 11: every value shown comes from a versioned artifact). The boards
 * describe; the generated model cards they link to carry the numbers. The one measured value
 * printed — the start/sit holdout accuracy against the best simple rule — is read from the
 * in-season build metadata when that build published it, and the sentence falls back to
 * words when it did not.
 *
 * The figures on the boards (tier bars, the bargain gap, the week strip, the range bars) are
 * labelled illustrations of the idea, not data, and are hidden from assistive technology;
 * each has a sentence saying what it shows.
 *
 * Navigation: previous / next buttons that wrap, one button per board, and the arrow keys
 * while focus is inside the carousel. The keydown handler is on the carousel, never global.
 * The current board's name is announced through a polite live region.
 *
 * A board is long on a phone, so below the phone breakpoint a second pair of buttons sits
 * under it, named for the board each one opens. Using them brings the new board's top back
 * into view, instantly rather than smoothly so reduced motion has nothing to opt out of.
 */

import { useCallback, useRef, useState } from "react";

import { DEFAULT_TRADE_RANGE } from "../data/state";
import type { InSeasonBundle } from "../data/ros";

const CARDS = "https://github.com/jeisey/jeisey-tiers/blob/main/models/cards";

type Status = "active" | "shadow" | "rule" | null;

const STATUS_LABEL: Readonly<Record<Exclude<Status, null>, string>> = {
  active: "Active duty",
  shadow: "Shadow ops",
  rule: "Simple rule",
};

interface Board {
  readonly id: string;
  readonly mission: string;
  readonly title: string;
  readonly codename: string | null;
  readonly status: Status;
  readonly question: string | null;
  readonly body: React.ReactNode;
}

function StatusTag({
  status,
}: {
  readonly status: Exclude<Status, null>;
}): React.JSX.Element {
  return (
    <span className={`hiw-status hiw-status-${status}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

function Panel({
  label,
  title,
  tone,
  children,
}: {
  readonly label: string;
  readonly title?: string;
  readonly tone?: "warn" | "good" | "muted";
  readonly children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div
      className={`hiw-panel chamfer${tone === undefined ? "" : ` hiw-panel-${tone}`}`}
    >
      <p className="hiw-label">{label}</p>
      {title !== undefined && <h4 className="hiw-panel-title">{title}</h4>}
      {children}
    </div>
  );
}

function CardLink({
  file,
  children,
}: {
  readonly file: string;
  readonly children: string;
}) {
  return (
    <p className="hiw-card-link">
      <a href={`${CARDS}/${file}`}>{children}</a>
    </p>
  );
}

function FlowNode({
  status,
  label,
  title,
  children,
}: {
  readonly status: Status;
  readonly label: string;
  readonly title: string;
  readonly children: React.ReactNode;
}): React.JSX.Element {
  return (
    <li
      className={`hiw-node chamfer${status === "shadow" ? " hiw-node-shadow" : ""}`}
    >
      <p className="hiw-label">
        {status !== null && (
          <span className={`hiw-mark hiw-mark-${status}`} aria-hidden="true" />
        )}
        {label}
      </p>
      <h4 className="hiw-panel-title">{title}</h4>
      <p>{children}</p>
    </li>
  );
}

function startSitRecord(inSeason: InSeasonBundle | null | undefined): string {
  const evaluation = inSeason?.metadata.weekly?.evaluation;
  const model = evaluation?.holdout_pair_accuracy;
  const baseline = evaluation?.best_baseline_pair_accuracy;
  if (
    model === undefined ||
    baseline === undefined ||
    !Number.isFinite(model) ||
    !Number.isFinite(baseline)
  ) {
    return "On a season it never trained on, it picked the better of two players more often than every simple shortcut it was tested against, including one that already uses the Vegas lines.";
  }
  const season = evaluation?.holdout_season;
  const when =
    season === undefined
      ? "a season it never trained on"
      : `the ${String(season)} season, which it never trained on`;
  return `On ${when}, it picked the better of two players ${(model * 100).toFixed(0)}% of the time, against ${(baseline * 100).toFixed(0)}% for the best simple shortcut. A coin flip is 50%.`;
}

function boards(inSeason: InSeasonBundle | null | undefined): readonly Board[] {
  return [
    {
      id: "map",
      mission: "Mission map",
      title: "Mission map",
      codename: null,
      status: null,
      question:
        "Six models and three tools. Each answers one question. Information only ever flows forward.",
      body: (
        <>
          <p className="hiw-row-label">Draft day: who should I pick?</p>
          <ol className="hiw-flow">
            <FlowNode status={null} label="Intel in" title="Football stats">
              Past seasons: snaps, targets, carries, age, draft pick, team. No
              experts, no draft rankings.
            </FlowNode>
            <FlowNode
              status="active"
              label="01 · Draft model"
              title="How good is he, really?"
            >
              A range for his season: games played × points per game.
            </FlowNode>
            <FlowNode
              status="active"
              label="02 · Simulation & tiers"
              title="Worth how much here?"
            >
              Plays the season thousands of times, scores him against a free
              fill-in, then groups players into tiers.
            </FlowNode>
            <FlowNode
              status="rule"
              label="03 · Bargain finder"
              title="Is he a steal?"
            >
              Our rank against where other people draft him. The only place
              crowd data is allowed.
            </FlowNode>
          </ol>
          <p className="hiw-row-label">
            During the season: who do I keep, start or trade?
          </p>
          <ol className="hiw-flow">
            <FlowNode status={null} label="Intel in" title="This season so far">
              Every completed week, plus the betting lines for the coming game.
            </FlowNode>
            <FlowNode
              status="active"
              label="04 · Rest of season"
              title="What's left in the tank?"
            >
              The draft question again, every week: how many points from here to
              the end?
            </FlowNode>
            <FlowNode
              status="active"
              label="05 · Start/Sit v1"
              title="Who plays this Sunday?"
            >
              A range of points for his next game, then the odds he beats the
              other guy.
            </FlowNode>
            <FlowNode
              status="shadow"
              label="06 · Start/Sit v2"
              title="v1 plus injury intel"
            >
              Adds news about his own offence's injuries. Being tested live, not
              yet shown.
            </FlowNode>
            <FlowNode
              status="rule"
              label="07 · Tools on top"
              title="Trade, waivers, Pick of the Week"
            >
              Calculators that read the numbers above and never change them.
            </FlowNode>
          </ol>
          <div className="hiw-callout chamfer">
            <p className="hiw-label">The one-way rule</p>
            <p>
              The &ldquo;how good is he&rdquo; models never see what the crowd
              thinks. So when they disagree with the crowd, it is a real second
              opinion, not an echo.
            </p>
          </div>
        </>
      ),
    },
    {
      id: "draft",
      mission: "Mission 01 · Draft day",
      title: "The draft model",
      codename: "intrinsic-cb-hurdle-v1",
      status: "active",
      question:
        "Before the season starts, how many fantasy points will this player score: worst case, best case and most likely?",
      body: (
        <>
          <div className="hiw-grid-3">
            <Panel label="Step 1" title="Will he suit up?">
              <p>
                First it estimates how many games he will actually play.
                Injuries and benchings are the biggest wildcard, so this gets
                its own question.
              </p>
            </Panel>
            <Panel label="Step 2" title="How good when he does?">
              <p>
                Then it estimates his points in a typical game, from his role,
                workload, efficiency, age and team.
              </p>
            </Panel>
            <Panel label="Step 3" title="Multiply, as a range">
              <p>
                Games × points per game. The result is a spread, not one number:
                a floor, a ceiling and the middle.
              </p>
            </Panel>
          </div>
          <div className="hiw-grid-2">
            <Panel label="Why split it in two?">
              <p>
                A large share of the players in a draft pool never play a game
                that season. A model that only asks &ldquo;how many
                points?&rdquo; spends its effort working that out. Asking
                &ldquo;will he play?&rdquo; separately makes it sharper.
              </p>
              <div className="hiw-allow">
                <div>
                  <p className="hiw-label hiw-good">Allowed intel</p>
                  <p>
                    Past stats, snaps, targets, carries, age, draft pick, team
                  </p>
                </div>
                <div>
                  <p className="hiw-label hiw-bad">Banned intel</p>
                  <p>
                    Expert rankings, average draft position, anything the crowd
                    thinks
                  </p>
                </div>
              </div>
            </Panel>
            <Panel label="Combat record">
              <p>
                Graded on past seasons it never saw, against a strong simple
                method built from last year&apos;s numbers. It put players in a
                better order and missed season totals by less. It only shipped
                because it won.
              </p>
              <CardLink file="intrinsic-cb-hurdle-v1.md">
                Every number: the model card
              </CardLink>
            </Panel>
          </div>
        </>
      ),
    },
    {
      id: "tiers",
      mission: "Mission 02 · Draft day",
      title: "Simulation, value and tiers",
      codename: "Monte Carlo · VORP · tier method",
      status: "active",
      question:
        "In my league, how much is this player worth, and who is he basically interchangeable with?",
      body: (
        <>
          <div className="hiw-grid-3">
            <Panel
              label="Step 1 · Replay"
              title="Run the season again and again"
            >
              <p>
                Take every player&apos;s range from the draft model and roll the
                dice for a whole season. Repeat thousands of times, like
                replaying a match to see every way it could go.
              </p>
            </Panel>
            <Panel label="Step 2 · Compare" title="Beat the free agent">
              <p>
                In each replay, fill every team&apos;s starting lineup. The best
                player left over at each position is the fill-in you could get
                for free. A player&apos;s value is how far he beats that
                fill-in.
              </p>
            </Panel>
            <Panel label="Step 3 · Group" title="Draw lines at the gaps">
              <p>
                Line players up by value. Wherever there is a real drop-off,
                draw a tier line. Nobody picks the number of tiers; the gaps
                decide.
              </p>
            </Panel>
          </div>
          <div className="hiw-grid-2">
            <Panel label="What tiers look like · illustration">
              <div className="hiw-tierbars" aria-hidden="true">
                {[
                  [96],
                  [78, 75, 73],
                  [55, 53, 52, 50],
                  [34, 32, 31, 29, 28],
                ].map((tier, t) => (
                  <div className="hiw-tier" key={t}>
                    <div className="hiw-tier-cols">
                      {tier.map((height, i) => (
                        <span
                          key={i}
                          style={{ height: `${String(height)}%` }}
                        />
                      ))}
                    </div>
                    <span className="hiw-tier-letter">
                      {["S", "A", "B", "C"][t]}
                    </span>
                  </div>
                ))}
              </div>
              <p>
                Each bar is a player&apos;s value; the gaps between groups are
                the tier breaks. Within a tier, any of them is about an equal
                pick.
              </p>
            </Panel>
            <Panel label="Why beating the fill-in matters">
              <p>
                Quarterbacks score the most raw points, but plenty of decent
                ones sit on waivers, so each is worth less than his total
                suggests. A running back who clearly beats the leftovers is
                worth more. Points <strong>above the free option</strong> are
                what count.
              </p>
              <p className="hiw-label hiw-warn">Honest caveat</p>
              <p>
                A fresh roll of the dice can move tier lines, especially deep in
                the draft. The top of the board is steady; the bottom wobbles.
                That wobble is measured and published.
              </p>
              <CardLink file="tier-method.md">
                How the tiers were tested
              </CardLink>
            </Panel>
          </div>
        </>
      ),
    },
    {
      id: "bargain",
      mission: "Mission 03 · Draft day",
      title: "The bargain finder",
      codename: "arbitrage A0 · a0_rank_gap_v1",
      status: "rule",
      question:
        "Does everyone else rate this player lower than we do, so I can wait and still get him?",
      body: (
        <>
          <div className="hiw-grid-3">
            <Panel label="Our rank">
              <p>Where our models say he belongs, from football alone.</p>
            </Panel>
            <Panel label="Where people draft him">
              <p>His average pick in real drafts on a public site.</p>
            </Panel>
            <Panel label="Verdict" tone="warn">
              <p>
                If the crowd takes him later than we would, he is a bargain
                worth targeting. If earlier, the crowd is paying up.
              </p>
            </Panel>
          </div>
          <div className="hiw-grid-2">
            <Panel label="The twist: early gaps count more · illustration">
              <p>
                Eight picks between #3 and #11 is a whole round of value. Eight
                picks between #180 and #188 is noise. So gaps are compared{" "}
                <strong>in proportion</strong> to where you are in the draft,
                and every player gets a 0–100 bargain score.
              </p>
              <div className="hiw-gaps" aria-hidden="true">
                <span>#3 to #11</span>
                <span className="hiw-gap-bar" style={{ width: "62%" }} />
                <span>#180 to #188</span>
                <span className="hiw-gap-bar" style={{ width: "4%" }} />
              </div>
            </Panel>
            <Panel label="Why it isn't machine learning yet">
              <p>
                Teaching a computer what a bargain looks like takes years of
                clean draft-day data. The history available mixes in drafts held
                after the season started, which is like grading a forecast with
                tomorrow&apos;s newspaper.
              </p>
              <p>
                So this stays a plain, open formula until there are several
                seasons of our own draft-day snapshots, and a learned version
                only replaces it if it wins.
              </p>
              <CardLink file="arbitrage-method-a0.md">
                The formula, in full
              </CardLink>
            </Panel>
          </div>
        </>
      ),
    },
    {
      id: "ros",
      mission: "Mission 04 · During the season",
      title: "Rest-of-season model",
      codename: "intrinsic-ros-v1",
      status: "active",
      question:
        "Knowing what has happened so far this year, how many points does he have left between now and the end of the season?",
      body: (
        <>
          <Panel label="A fresh checkpoint every week · for example, after week 6">
            <div className="hiw-weeks" aria-hidden="true">
              {Array.from({ length: 17 }, (_, i) => (
                <span
                  key={i}
                  className={i < 6 ? "hiw-week-seen" : "hiw-week-ahead"}
                >
                  {String(i + 1)}
                </span>
              ))}
            </div>
            <p>
              Solid: weeks already played, which it can see. Outlined: weeks
              left, which it predicts.
            </p>
          </Panel>
          <div className="hiw-grid-3">
            <Panel label="Same playbook" title="Two questions again">
              <p>
                Like the draft model: how many of the remaining games will he
                play, and how many points per game when he does? Now it also
                sees this year&apos;s form, role and team. Most players in the
                pool will not play again, so splitting the question still pays
                off.
              </p>
            </Panel>
            <Panel label="New yardstick" title="Beat the waiver wire">
              <p>
                Mid-season, the free option is the best player{" "}
                <em>nobody has on a roster</em>. Value is measured against him,
                and players are tiered the same way as on draft day.
              </p>
              <p className="hiw-label hiw-bad">Banned intel</p>
              <p>
                Injury reports and depth charts: there is no clean history to
                test them on, so it uses &ldquo;weeks since his last game&rdquo;
                instead.
              </p>
            </Panel>
            <Panel label="Combat record">
              <p>
                Graded on past seasons, checkpoint by checkpoint, against simple
                benchmarks such as &ldquo;keep scoring at his current
                rate&rdquo;. It ordered players better and missed by less.
              </p>
              <CardLink file="intrinsic-ros-v1.md">
                Every number: the model card
              </CardLink>
            </Panel>
          </div>
        </>
      ),
    },
    {
      id: "startsit-v1",
      mission: "Mission 05 · During the season",
      title: "Start/Sit v1",
      codename: "weekly-startsit-v1",
      status: "active",
      question:
        "I have one spot and two players. Which one should I start this week?",
      body: (
        <>
          <div className="hiw-grid-2">
            <Panel label="What you see · illustration">
              <div className="hiw-ranges" aria-hidden="true">
                <span>Player A</span>
                <span className="hiw-track">
                  <span
                    className="hiw-range"
                    style={{ left: "18%", width: "52%" }}
                  />
                  <span className="hiw-notch" style={{ left: "41%" }} />
                </span>
                <span>Player B</span>
                <span className="hiw-track">
                  <span
                    className="hiw-range hiw-range-alt"
                    style={{ left: "10%", width: "70%" }}
                  />
                  <span className="hiw-notch" style={{ left: "35%" }} />
                </span>
              </div>
              <p>
                Each bar is the range of points he could score, from a bad week
                on the left to a great one on the right; the notch is the most
                likely. B swings wider: a bigger ceiling and a lower floor. The
                page turns that into the chance A outscores B, and your chance
                of winning the week with each.
              </p>
            </Panel>
            <Panel label="Intel it reads">
              <ul className="hiw-chips">
                {[
                  "Recent form",
                  "Snaps and targets",
                  "Track record",
                  "His offence",
                  "Vegas over/under",
                  "Point spread",
                  "Home or away",
                  "Rest days",
                  "Dome or open air",
                  "Opponent's defence against his position",
                ].map((chip) => (
                  <li key={chip}>{chip}</li>
                ))}
              </ul>
              <p className="hiw-label hiw-warn">Assumes he plays</p>
              <p>
                It predicts points <em>if</em> he takes the field. Whether he
                plays is shown separately, from the official injury report and
                how often players with that tag actually suit up.
              </p>
            </Panel>
          </div>
          <div className="hiw-grid-2">
            <Panel label="Combat record">
              <p>{startSitRecord(inSeason)}</p>
              <p>
                One week of football is very random, so a small edge, used all
                season, adds up.
              </p>
              <CardLink file="weekly-startsit-v1.md">
                Every number: the model card
              </CardLink>
            </Panel>
            <Panel label="Rules of the field">
              <p>
                <strong>Bye week:</strong> no projection, marked
                &ldquo;bye&rdquo;.
              </p>
              <p>
                <strong>No betting line yet:</strong> no projection, marked
                &ldquo;lines pending&rdquo;. It never invents one.
              </p>
              <p>
                <strong>Game kicked off:</strong> locked.
              </p>
              <p>
                <strong>Why this week:</strong> what moved him up or down
                against his usual week, such as a soft defence or a high-scoring
                game expected.
              </p>
            </Panel>
          </div>
        </>
      ),
    },
    {
      id: "startsit-v2",
      mission: "Mission 06 · During the season",
      title: "Start/Sit v2",
      codename: "weekly-startsit-v2",
      status: "shadow",
      question:
        "Does knowing about weather and injuries make the start/sit call any better?",
      body: (
        <>
          <Panel label="Tryouts · three new kinds of intel, each had to beat v1 on its own">
            <div className="hiw-grid-3">
              <div className="hiw-tryout hiw-tryout-in">
                <p className="hiw-label hiw-good">Selected</p>
                <h4 className="hiw-panel-title">His offence&apos;s health</h4>
                <p>
                  Linemen out, quarterback out, and how many targets and carries
                  injured teammates leave behind. It won in every test season,
                  mostly by helping with running backs.
                </p>
              </div>
              <div className="hiw-tryout">
                <p className="hiw-label">Cut</p>
                <h4 className="hiw-panel-title">Weather at kickoff</h4>
                <p>
                  Wind, temperature and rain from real forecasts. No measurable
                  gain: the betting lines already account for the weather.
                </p>
              </div>
              <div className="hiw-tryout">
                <p className="hiw-label">Cut</p>
                <h4 className="hiw-panel-title">
                  Opposing defence&apos;s health
                </h4>
                <p>
                  Missing cornerbacks, safeties and linemen. No measurable gain
                  either, for the same reason.
                </p>
              </div>
            </div>
          </Panel>
          <div className="hiw-grid-2">
            <Panel label="What shadow ops means">
              <p>
                v2 makes predictions quietly next to v1 every week, but nobody
                sees them. Each one is locked into a record{" "}
                <strong>before kickoff</strong>, so it cannot be changed after
                the fact.
              </p>
              <p>
                The edge it showed in testing is small but steady. It still has
                to prove itself on games that had not been played when the rules
                were written.
              </p>
            </Panel>
            <Panel label="The verdict, once there is enough evidence">
              <ol className="hiw-steps">
                <li>
                  Wait for a minimum number of complete weeks and predictions,
                  set in advance.
                </li>
                <li>
                  Compare v2 with v1 on those real games, using a test written
                  beforehand.
                </li>
                <li>
                  <strong>Promote</strong> if clearly better,{" "}
                  <strong>reject</strong> if clearly worse; otherwise &ldquo;not
                  enough evidence&rdquo; and v1 keeps the job.
                </li>
              </ol>
              <CardLink file="weekly-startsit-v2.md">
                The tryout results: the model card
              </CardLink>
            </Panel>
          </div>
        </>
      ),
    },
    {
      id: "tools",
      mission: "Mission 07 · Support",
      title: "Tools built on top",
      codename: null,
      status: "rule",
      question:
        "These are not models. They learn nothing: they are calculators that read the rest-of-season numbers and never change them.",
      body: (
        <div className="hiw-grid-3">
          <Panel label="Trade tab" title="Fair trades">
            <p className="hiw-quote">
              &ldquo;Who could I get for my guy without getting fleeced?&rdquo;
            </p>
            <p>
              Adds up each player&apos;s remaining value (points above the
              waiver wire) and shows packages worth about the same as yours,
              within {`${String(DEFAULT_TRADE_RANGE)}%`} by default. You choose
              what matters most: steady value, a high ceiling or a safe floor.
            </p>
            <p className="hiw-label hiw-warn">Fine print</p>
            <p>
              Two good players are not one great starter. Each package shows its
              best single player and how many roster spots it uses.
            </p>
          </Panel>
          <Panel label="Opportunity board" title="Waiver radar">
            <p className="hiw-quote">
              &ldquo;Who is everyone picking up, and are they right?&rdquo;
            </p>
            <p>
              Puts our value next to how many managers added or dropped a player
              on Sleeper. Crowd activity can decide{" "}
              <strong>who is shown</strong>; it can never move a player&apos;s
              value or rank.
            </p>
            <p className="hiw-label hiw-warn">Fine print</p>
            <p>
              It never blends the two into one score: pickups and value measure
              different things.
            </p>
          </Panel>
          <Panel label="Pick of the Week" title="Top pickup">
            <p className="hiw-quote">
              &ldquo;Who is the best player I can probably still grab at each
              position?&rdquo;
            </p>
            <p>
              One waiver target each at QB, RB, WR and TE. Lots of pickups show
              he is widely available, because a player already on nearly every
              roster cannot be added much. Among available players, our model
              sets the order.
            </p>
            <p className="hiw-label hiw-warn">Fine print</p>
            <p>
              No public source gives a true &ldquo;% rostered&rdquo;, so it
              never shows one. It shows the pickup count and its time window
              instead.
            </p>
          </Panel>
        </div>
      ),
    },
    {
      id: "rules",
      mission: "Mission 08 · Standing orders",
      title: "Rules of engagement",
      codename: null,
      status: null,
      question:
        "Why you can trust these numbers: every model here plays by the same six rules.",
      body: (
        <ol className="hiw-rules">
          {[
            [
              "No peeking at the future",
              "A prediction for week 7 only uses what was known by week 6. Automated tests fail the build if anything from the future slips in.",
            ],
            [
              "No copying the crowd",
              "The “how good is he” models never see expert rankings or draft positions. Otherwise “we disagree with the crowd” would mean nothing.",
            ],
            [
              "Beat the simple answer",
              "Every model is tested against a simple shortcut, such as last year's stats. If it cannot win, it does not ship.",
            ],
            [
              "Write the test first",
              "The pass and fail rules are written down and locked before the results are seen, so nobody can move the goalposts.",
            ],
            [
              "Tested on unseen seasons",
              "Each model is graded on seasons it was not trained on, the way a forecaster is judged on tomorrow's weather, not yesterday's.",
            ],
            [
              "Ranges, not promises",
              "Every projection is a spread from a bad week to a great one. Football is random; the models say so instead of hiding it.",
            ],
          ].map(([title, text], i) => (
            <li key={title} className="hiw-panel chamfer">
              <span className="hiw-rule-num" aria-hidden="true">
                {String(i + 1).padStart(2, "0")}
              </span>
              <div>
                <h4 className="hiw-panel-title">{title}</h4>
                <p>{text}</p>
              </div>
            </li>
          ))}
        </ol>
      ),
    },
  ];
}

export function HowItWorks({
  inSeason,
}: {
  readonly inSeason?: InSeasonBundle | null | undefined;
}): React.JSX.Element {
  const all = boards(inSeason);
  const count = all.length;
  const [index, setIndex] = useState(0);
  const topRef = useRef<HTMLDivElement>(null);
  const go = useCallback(
    (next: number) => {
      setIndex(((next % count) + count) % count);
    },
    [count],
  );
  const board = all[index] ?? all[0];
  if (board === undefined) throw new Error("How it works has no boards");
  const previous = all[(index - 1 + count) % count] ?? board;
  const next = all[(index + 1) % count] ?? board;

  function goFromFoot(target: number): void {
    go(target);
    const top = topRef.current;
    // Optional-called: jsdom, where the unit tests run, has no layout and no scrollIntoView.
    if (top !== null && typeof top.scrollIntoView === "function") top.scrollIntoView({ block: "start" });
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      go(index + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      go(index - 1);
    }
  }

  return (
    <div
      className="hiw"
      role="region"
      aria-roledescription="carousel"
      aria-label="How the models work"
      onKeyDown={onKeyDown}
    >
      <div className="hiw-nav" ref={topRef}>
        <button
          type="button"
          className="hiw-arrow"
          aria-label="Previous board"
          onClick={() => {
            go(index - 1);
          }}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <path
              d="M10 3 5 8l5 5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
          </svg>
        </button>
        <ol className="hiw-dots">
          {all.map((b, i) => (
            <li key={b.id}>
              <button
                type="button"
                className="hiw-dot"
                aria-label={`Board ${String(i + 1)}: ${b.title}`}
                aria-current={i === index ? "true" : undefined}
                onClick={() => {
                  go(i);
                }}
              />
            </li>
          ))}
        </ol>
        <span className="hiw-count" aria-hidden="true">
          {`${String(index + 1).padStart(2, "0")} / ${String(count).padStart(2, "0")}`}
        </span>
        <button
          type="button"
          className="hiw-arrow"
          aria-label="Next board"
          onClick={() => {
            go(index + 1);
          }}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <path
              d="m6 3 5 5-5 5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
          </svg>
        </button>
      </div>
      <p className="visually-hidden" aria-live="polite">
        {`Board ${String(index + 1)} of ${String(count)}: ${board.title}`}
      </p>
      <article
        key={board.id}
        className={`hiw-board chamfer${board.status === "shadow" ? " hiw-board-shadow" : ""}`}
        aria-roledescription="slide"
        aria-label={`${String(index + 1)} of ${String(count)}: ${board.title}`}
      >
        <header className="hiw-board-head">
          <div>
            <p className="hiw-label">{board.mission}</p>
            <h3 className="hiw-title">{board.title}</h3>
            {board.codename !== null && (
              <p className="hiw-codename">{board.codename}</p>
            )}
          </div>
          {board.status !== null && <StatusTag status={board.status} />}
        </header>
        {board.question !== null && (
          <p className="hiw-question">{board.question}</p>
        )}
        <div className="hiw-body">{board.body}</div>
      </article>
      <div className="hiw-foot">
        <button
          type="button"
          className="hiw-foot-button"
          aria-label={`Previous: ${previous.title}`}
          onClick={() => {
            goFromFoot(index - 1);
          }}
        >
          <span className="hiw-label">Previous</span>
          <span className="hiw-foot-title">{previous.title}</span>
        </button>
        <button
          type="button"
          className="hiw-foot-button hiw-foot-next"
          aria-label={`Next: ${next.title}`}
          onClick={() => {
            goFromFoot(index + 1);
          }}
        >
          <span className="hiw-label">Next</span>
          <span className="hiw-foot-title">{next.title}</span>
        </button>
      </div>
    </div>
  );
}
