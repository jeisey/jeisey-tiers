"""Phase-11 rest-of-season intrinsic model (`intrinsic-ros-v1`).

The package is deliberately parallel to, and separate from, the preseason model. It shares
the scoring engine, the simulation and allocation machinery, the metric definitions and the
Phase-2 feature table; it shares no target, no fold definition and no promotion rule, because
"how many points will this player score this season" and "how many points are left in this
season" are different questions with different information environments.

Read the modules in this order:

``cutoff``
    The frozen point-in-time rule: what a snapshot through week N may read.
``panel``
    The dense weekly panel every cumulative quantity is read off.
``labels``
    Rest-of-season targets, reconciled against the existing scoring engine.
``dictionary``
    Every model input with its availability rule.
``features``
    The in-season feature block, computed only from weeks at or before the cutoff.
``dataset``
    Snapshots joined to labels, with the sealed season already removed.
``folds`` / ``holdout``
    Chronological season-blocked evaluation and the sealed final season.
``baselines`` / ``candidates``
    The declared simple baselines and the hurdle candidate.
``gate``
    The promotion rule, frozen before the comparison ran.
``attribution``
    Offline per-player feature attribution, by model component.
``experiment`` / ``report``
    Orchestration and serialization.
"""

from __future__ import annotations

from ffdraft.ros.cutoff import (
    ROS_CUTOFF_RULE,
    ROS_CUTOFF_RULE_VERSION,
    RosCutoff,
    season_cutoffs,
)
from ffdraft.ros.dictionary import (
    ROS_FEATURE_SCHEMA_VERSION,
    ROS_FEATURE_SET_VERSION,
    RosFeatureSelection,
    ros_feature_schema_hash,
    ros_feature_selection,
)
from ffdraft.ros.labels import ROS_LABEL_VERSION, build_ros_labels, reconcile_ros_labels
from ffdraft.ros.panel import PANEL_VERSION, build_weekly_panel

__all__ = [
    "PANEL_VERSION",
    "ROS_CUTOFF_RULE",
    "ROS_CUTOFF_RULE_VERSION",
    "ROS_FEATURE_SCHEMA_VERSION",
    "ROS_FEATURE_SET_VERSION",
    "ROS_LABEL_VERSION",
    "RosCutoff",
    "RosFeatureSelection",
    "build_ros_labels",
    "build_weekly_panel",
    "reconcile_ros_labels",
    "ros_feature_schema_hash",
    "ros_feature_selection",
    "season_cutoffs",
]
