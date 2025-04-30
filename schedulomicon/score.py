def aggregate_score_functions(variables, grid_and_functions):

    obj = 0
    for grid, fn in grid_and_functions:
        obj += fn(variables[grid])

    return obj


def objective_from_score_dict(variables, scores, default_score=None):

    if default_score is None:
        assert set(variables.keys()) == set(scores.keys())

    obj = 0

    for k in variables:
        obj += variables[k] * scores.get(k, 0)

    return obj


def accumulate_score_res_block_scores(score_dict, resident_block_scores, rotation):
    for resident, block_scores in resident_block_scores.items():
        for block, score in block_scores.items():
            score_dict[(resident, block, rotation)] += score


def accumulate_score_res_rot_scores(score_dict, resident_rot_scores):

    blocks = set([b for (re, b, ro) in score_dict.keys()])

    for resident, rot_scores in resident_rot_scores.items():
        for rot, score in rot_scores.items():
            for block in blocks:
                score_dict[(resident, block, rot)] += score


def score_dict_from_df(rankings, residents, blocks, rotations, block_resident_ranking):

    for res, rnk in rankings.items():
        for rot in rnk:
            assert rot in rotations, f"Rotation '{rot}' not found in YAML specification."

    scores = {}
    for res in residents:
        for block in blocks:
            for rot in rotations:
                scores[(res, block, rot)] = 0

    accumulate_score_res_rot_scores(scores, rankings)

    if block_resident_ranking is not None:
        rotation, rot_blk_scores = block_resident_ranking
        accumulate_score_res_block_scores(scores, rot_blk_scores, rotation)

    return scores
