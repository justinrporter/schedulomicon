import pytest

from . import score


def test_objective_from_score_dict_default_score_used_for_missing_keys():
    variables = {'a': 2, 'b': 3}
    scores = {'a': 1}

    obj = score.objective_from_score_dict(variables, scores, default_score=5)

    # 'a' contributes 1 * 2; 'b' is absent from scores so contributes 5 * 3
    assert obj == 1 * 2 + 5 * 3


def test_objective_from_score_dict_default_score_zero_unchanged():
    variables = {'a': 2, 'b': 3}
    scores = {'a': 1}

    obj = score.objective_from_score_dict(variables, scores, default_score=0)

    assert obj == 1 * 2


def test_objective_from_score_dict_default_none_matching_keys():
    variables = {'a': 2, 'b': 3}
    scores = {'a': 1, 'b': -1}

    obj = score.objective_from_score_dict(variables, scores)

    assert obj == 1 * 2 + -1 * 3


def test_objective_from_score_dict_default_none_asserts_on_mismatch():
    variables = {'a': 2, 'b': 3}
    scores = {'a': 1}

    with pytest.raises(AssertionError):
        score.objective_from_score_dict(variables, scores, default_score=None)
