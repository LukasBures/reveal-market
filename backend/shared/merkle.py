from __future__ import annotations

from typing import Iterable

from shared.poseidon import BATCH_SIZE, MERKLE_DEPTH, int_to_bytes32, poseidon_t3

ZERO_LEAF = b"\x00" * 32


def _hash_pair(left: bytes, right: bytes) -> bytes:
    left_int = int.from_bytes(left, "big")
    right_int = int.from_bytes(right, "big")
    return int_to_bytes32(poseidon_t3(left_int, right_int))


def build_merkle_root_and_paths(
    leaves: list[bytes],
    *,
    depth: int = MERKLE_DEPTH,
    pad_to: int = BATCH_SIZE,
    pad_leaf: bytes = ZERO_LEAF,
) -> tuple[bytes, list[list[bytes]]]:
    """Build a fixed-depth Poseidon Merkle tree and return root + per-leaf sibling paths.

    Leaves are padded with zero leaves to `pad_to` (default 256). Paths are only generated for the
    provided leaves in order.
    """

    if not leaves:
        return b"", []
    expected_size = 1 << depth
    if pad_to != expected_size:
        raise ValueError("pad_to must equal 2**depth")
    if len(leaves) > pad_to:
        raise ValueError("too many leaves for merkle tree")

    padded = leaves + [pad_leaf] * (pad_to - len(leaves))
    layers: list[list[bytes]] = [padded]

    for _ in range(depth):
        prev = layers[-1]
        next_level: list[bytes] = []
        for i in range(0, len(prev), 2):
            next_level.append(_hash_pair(prev[i], prev[i + 1]))
        layers.append(next_level)

    root = layers[-1][0]
    paths: list[list[bytes]] = []
    for leaf_index in range(len(leaves)):
        index = leaf_index
        siblings: list[bytes] = []
        for level in range(depth):
            sibling_index = index ^ 1
            siblings.append(layers[level][sibling_index])
            index //= 2
        paths.append(siblings)

    return root, paths


def build_merkle_path(
    leaves: list[bytes],
    target_index: int,
    *,
    depth: int = MERKLE_DEPTH,
    pad_to: int = BATCH_SIZE,
    pad_leaf: bytes = ZERO_LEAF,
) -> list[bytes]:
    """Return the merkle sibling path for one leaf index."""

    if target_index < 0:
        raise ValueError("target_index must be >= 0")
    if target_index >= len(leaves):
        raise ValueError("target_index out of range")
    _, paths = build_merkle_root_and_paths(leaves, depth=depth, pad_to=pad_to, pad_leaf=pad_leaf)
    return paths[target_index]


def chunk_batches(values: Iterable[int], batch_size: int = BATCH_SIZE) -> list[list[int]]:
    batches: list[list[int]] = []
    current: list[int] = []
    for value in values:
        current.append(value)
        if len(current) >= batch_size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches
