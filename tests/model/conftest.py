"""Fixtures specific to the modelling tests.

The synthetic feature and label builders live in the root ``tests/conftest.py``, because
Phase 4's integration tests need them too - a current-season build needs a trained
production model, and a model needs a training set.
"""

from __future__ import annotations

import pytest

from ffdraft.features.dictionary import FEATURE_DICTIONARY, FeatureRole


@pytest.fixture(scope="session")
def model_input_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in FEATURE_DICTIONARY if spec.role.is_model_input)


@pytest.fixture(scope="session")
def indicator_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in FEATURE_DICTIONARY if spec.role is FeatureRole.INDICATOR)
