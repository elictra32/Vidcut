from core.cutmap import CutPiece, map_window, pieces_from_dicts

PIECES = [CutPiece(10, 20, 0), CutPiece(30, 50, 10)]  # 10 s then 20 s kept


def test_window_inside_a_piece_moves_by_the_offset():
    assert map_window(PIECES, 12, 15) == (2, 5)
    assert map_window(PIECES, 35, 40) == (15, 20)


def test_window_in_removed_time_is_dropped():
    assert map_window(PIECES, 21, 29) is None
    assert map_window(PIECES, 0, 9) is None


def test_window_spanning_a_cut_keeps_the_larger_part():
    assert map_window(PIECES, 18, 33) == (10, 13)  # 2 s in the first piece vs 3 s in the second
    assert map_window(PIECES, 19, 40) == (10, 20)  # 1 s vs 10 s


def test_pieces_from_dicts_sorts_and_skips_empty():
    ps = pieces_from_dicts([{"src_start": 30, "src_end": 50, "out_start": 10}, {"src_start": 5, "src_end": 5, "out_start": 0},
                            {"src_start": 10, "src_end": 20, "out_start": 0}])
    assert [p.src_start for p in ps] == [10, 30]
