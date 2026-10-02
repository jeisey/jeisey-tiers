# Baseline Analysis — `borisachen/fftiers` (historical study)

> **Historical.** An archived research note from the original specification bundle. It records how one existing open-source tier generator worked on 2026-08-12 and which requirements that analysis informed. It is not a product comparison and is not maintained; the external repository may have changed since.

Research snapshot: 2026-08-12.

Repository studied: https://github.com/borisachen/fftiers

## Purpose

The study recorded how an established consensus-based tier generator works, so that this project's requirements for independent modelling, tier discovery and operations could be stated against a concrete reference.

## Repository observations

The repository README states that it contains the code used to generate the fantasy-football tiers behind borischen.co and that its data is exclusively from FantasyPros.

The current repository remains a mixed R/Python codebase. Relevant files include:

- `src/main.R`
- `src/ff-functions.R`
- `src/fp_api.py`
- older deployment/cron/S3 scripts

The current `main.R` snapshot is explicitly season-coded for 2025, including a hardcoded Week-1 Tuesday and filesystem paths under `~/projects/fftiers`.

## Tier methodology in the code

`ff-functions.R` reads rank-oriented FantasyPros data with columns such as:

- Rank
- Player.Name
- Best.Rank
- Worst.Rank
- Avg.Rank
- Std.Dev

Inside the main plotting function, it constructs a dataframe using `Avg.Rank` and calls:

```r
Mclust(df, G=k)
```

where `k` is passed manually by chart/position call. The resulting mixture-cluster class becomes the tier.

The chart then displays average expert rank and a dispersion/error bar based on expert rank standard deviation.

## Manual tier-count configuration

`main.R` calls `draw.tiers` with manually selected `k` values by position/scoring, for example different fixed values for QB, RB, WR, TE and flex ranges. Pre-draft overall rankings are split into blocks and clustered with manually supplied cluster counts.

This is a reasonable visualization of expert-consensus structure, but it does not independently forecast player fantasy outcomes or determine tier count entirely from football-value evidence.

## Operational observations

The baseline code currently contains:

- season/year hardcoding;
- host/user-specific filesystem paths;
- R + Python process calls;
- older cron/deployment assumptions;
- source dependency on FantasyPros;
- output files geared around static images/text/CSV rather than an interactive data application.

## Requirements this study informed

The analysis fed these requirements into the V1 specification (`PRD.md`, Part B):

### Method

- independent football-outcome modeling;
- probabilistic distributions;
- league-specific replacement value;
- natural tier segmentation with no fixed tier count;
- out-of-time validation;
- explicit arbitrage modeling.

### Data

- broader public/free football feature base;
- source adapters and identity contracts;
- source freshness/quality metadata;
- market snapshot history.

### Product

- interactive S-tier-style board;
- interactive Draft Rail arbitrage chart;
- sortable/filterable/searchable tables;
- CSV exports;
- scoring/league presets;
- methodology/model/source transparency.

### Operations

- GitHub-native CI/CD;
- daily scheduled update;
- locked dependencies;
- automated tests;
- fail-safe deployment;
- model/artifact versioning.

## Scope of the comparison

The studied project is primarily a consensus-ranking tier visualization and solves a different problem. This note describes its method; it does not evaluate it as a product.
