"""Chessboard geometry, row-major corner IDs, no rendering dependency."""
from dataclasses import dataclass

import numpy as np

from gimbal_lab.domain.models import Board


def readonly(array):
    """Own immutable backing bytes, preventing callers from re-enabling writes."""
    array = np.ascontiguousarray(array)
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


@dataclass(frozen=True)
class BoardGeometry:
    columns: int
    rows: int
    spacing_mm: float
    corners_local_mm: np.ndarray
    squares_local_mm: np.ndarray
    square_is_dark: np.ndarray
    outer_vertices_local_mm: np.ndarray

    @classmethod
    def from_config(cls, board: Board):
        board.validate()
        d = board.spacing_mm
        corners = [[column * d, row * d, 0] for row in range(board.rows) for column in range(board.columns)]
        squares, dark = [], []
        for row in range(board.rows + 1):
            for column in range(board.columns + 1):
                x, y = (column - 1) * d, (row - 1) * d
                squares.append([[x, y, 0], [x + d, y, 0], [x + d, y + d, 0], [x, y + d, 0]])
                dark.append((row + column) % 2 == 1)
        outer = [[-d, -d, 0], [board.columns * d, -d, 0],
                 [board.columns * d, board.rows * d, 0], [-d, board.rows * d, 0]]
        return cls(board.columns, board.rows, d, readonly(np.array(corners, dtype=float)),
                   readonly(np.array(squares, dtype=float)), readonly(np.array(dark)),
                   readonly(np.array(outer, dtype=float)))

