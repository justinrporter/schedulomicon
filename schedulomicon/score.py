def aggregate_score_functions(variables, grid_and_functions):
    """
    Aggregate multiple scoring functions across different variable grids.

    Args:
        variables (dict): A dictionary mapping grid names to variable dictionaries.
                         Each variable dictionary maps assignment tuples to CP-SAT variables.
        grid_and_functions (list): A list of tuples (grid_name, function), where:
                                  - grid_name (str): The name of the variable grid to score
                                  - function (callable): A scoring function that takes a variable
                                    dictionary and returns a numeric score

    Returns:
        int: The sum of all scoring functions applied to their respective grids
    """
    obj = 0
    for grid, fn in grid_and_functions:
        obj += fn(variables[grid])

    return obj


def objective_from_score_dict(variables, scores, default_score=None):
    """
    Create an objective function from a dictionary of scores.

    Args:
        variables (dict):
            A dictionary mapping assignment tuples to CP-SAT variables.
            Typically (resident, block, rotation) tuples to binary variables.
        scores (dict):
            A dictionary mapping the same assignment tuples to numeric scores.
        default_score (int, optional):
            The default score to use for variables not found in scores. If
            None, asserts that variables and scores have the same keys.

    Returns:
        int: The weighted sum of variables multiplied by their respective scores
    """
    if default_score is None:
        assert set(variables.keys()) == set(scores.keys())

    obj = 0

    for k in variables:
        obj += variables[k] * scores.get(k, 0)

    return obj


def accumulate_score_res_block_scores(score_dict, resident_block_scores, rotation):
    """
    Add block-specific scores for a single rotation to a score dictionary.

    Args:
        score_dict (dict): A dictionary mapping (resident, block, rotation) tuples to scores.
                          Will be modified in place.
        resident_block_scores (dict): A nested dictionary where:
                                     - outer keys are resident names
                                     - inner keys are block names
                                     - values are numeric scores
        rotation (str): The rotation to apply these scores to
    """
    for resident, block_scores in resident_block_scores.items():
        for block, score in block_scores.items():
            score_dict[(resident, block, rotation)] += score


def accumulate_score_res_rot_scores(score_dict, resident_rot_scores):
    """
    Add rotation-specific scores for all blocks to a score dictionary.

    Args:
        score_dict (dict): A dictionary mapping (resident, block, rotation) tuples to scores.
                          Will be modified in place. Used to identify all available blocks.
        resident_rot_scores (dict): A nested dictionary where:
                                   - outer keys are resident names
                                   - inner keys are rotation names
                                   - values are numeric scores
    """
    blocks = set([b for (re, b, ro) in score_dict.keys()])

    for resident, rot_scores in resident_rot_scores.items():
        for rot, score in rot_scores.items():
            for block in blocks:
                score_dict[(resident, block, rot)] += score


def score_dict_from_df(rankings, residents, blocks, rotations, block_resident_ranking):
    """
    Create a score dictionary from rankings data and optional block-specific scores.

    Args:
        rankings (dict):
            A dictionary mapping resident names to another dictionary
            that maps rotation names to preference scores.
        residents (list): List of all resident names.
        blocks (list): List of all block names.
        rotations (list): List of all rotation names.
        block_resident_ranking (tuple, optional):
            If provided, a tuple containing:
                - rotation (str): The rotation to apply block-specific scores to
                - rot_blk_scores (dict): A nested dictionary of resident->block->score

    Returns:
        dict: A dictionary mapping (resident, block, rotation) tuples to combined scores.
              Includes both rotation preferences (applied to all blocks) and
              block-specific preferences (for a single rotation).

    Raises:
        AssertionError: If a rotation in rankings is not found in the rotations list.
    """
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
