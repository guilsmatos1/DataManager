"""Golden tests for streak formulas."""

from __future__ import annotations

from trademachine.metrics.formulas.streaks import max_consec_losses, max_consec_wins

PNLS = [100.0, -50.0, -75.0, 200.0, 150.0, -10.0, 50.0]
# wins:   1         0    0     1      1     0    1
# losses: 0         1    1     0      0     1    0


class TestMaxConsecWins:
    def test_basic(self) -> None:
        # best streak: idx 3,4 (200, 150) = 2 consecutive
        assert max_consec_wins(PNLS) == 2

    def test_all_wins(self) -> None:
        assert max_consec_wins([10.0, 20.0, 30.0]) == 3

    def test_all_losses(self) -> None:
        assert max_consec_wins([-10.0, -20.0]) == 0

    def test_empty(self) -> None:
        assert max_consec_wins([]) == 0

    def test_single_win(self) -> None:
        assert max_consec_wins([100.0]) == 1


class TestMaxConsecLosses:
    def test_basic(self) -> None:
        # best streak: idx 1,2 (-50, -75) = 2 consecutive
        assert max_consec_losses(PNLS) == 2

    def test_all_losses(self) -> None:
        assert max_consec_losses([-10.0, -20.0, -5.0]) == 3

    def test_all_wins(self) -> None:
        assert max_consec_losses([10.0, 20.0]) == 0

    def test_empty(self) -> None:
        assert max_consec_losses([]) == 0

    def test_single_loss(self) -> None:
        assert max_consec_losses([-100.0]) == 1
