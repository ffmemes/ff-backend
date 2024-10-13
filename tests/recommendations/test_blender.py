from src.recommendations.blender import blend


def test_blender_few_candidates():
    candidates_dict = {
        'engine_1': [
            {'id': 1},
            {'id': 2},
        ],
        'engine_2': [
            {'id': 3},
            {'id': 4},
        ],
    }
    weights_dict = {
        'engine_1': 1,
        'engine_2': 1,
    }

    res = blend(candidates_dict, weights_dict)
    assert(len(res) == 4)


def test_blender_item_intersection_and_zero_weight():

    candidates_dict = {
        'engine_1': [
            {'id': 1},
            {'id': 2},
            {'id': 3},
        ],
        'engine_2': [
            {'id': 3},
            {'id': 4},
        ],
    }
    weights_dict = {
        'engine_1': 1,
        'engine_2': 0,
    }

    res = blend(candidates_dict, weights_dict)
    assert(len(res) == 4)
    assert res[0]['id'] == 1
    assert res[1]['id'] == 2
    assert res[2]['id'] == 3
    assert res[3]['id'] == 4


def test_blender_stats_test():
    candidates_dict = {
        'engine_1': [
            {'id': 1},
            {'id': 2},
        ],
        'engine_2': [
            {'id': 3},
            {'id': 4},
        ],
    }
    weights_dict = {
        'engine_1': 1,
        'engine_2': 3,
    }

    engine_1_cnt = 0
    n_iter = 10000
    for i in range(n_iter):
        res = blend(candidates_dict, weights_dict, random_seed=(i + 10000))
        if res[0]['id'] == 1:
            engine_1_cnt += 1
    assert abs(engine_1_cnt / n_iter - 0.25) < 0.01


def test_blender_fixed_pos():
    candidates_dict = {
        'engine_1': [
            {'id': 1},
            {'id': 2},
        ],
        'engine_2': [
            {'id': 3},
            {'id': 4},
        ],
    }
    weights_dict = {
        'engine_1': 0,
        'engine_2': 1,
    }

    fixed_pos = {0: 'engine_1'}

    res = blend(candidates_dict, weights_dict, fixed_pos=fixed_pos, random_seed=42)
    assert res[0]['id'] == 1


def test_blender_limit():

    candidates_dict = {
        'engine_1': [
            {'id': 1},
            {'id': 2},
        ],
        'engine_2': [
            {'id': 3},
            {'id': 4},
        ],
    }
    weights_dict = {
        'engine_1': 1,
        'engine_2': 1,
    }

    res = blend(candidates_dict, weights_dict, limit=2)
    assert len(res) == 2
