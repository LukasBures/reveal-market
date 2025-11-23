from __future__ import annotations


def build_merkle_root_and_paths(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
    """Build a keccak-based binary Merkle tree and return root and per-leaf sibling paths.

    Leaves are duplicated when odd to maintain full binary levels. Returns (root, paths) where
    paths[i] is the sibling list for leaf i from bottom-up.
    """

    if not leaves:
        return b"", []

    # Initialize paths for each leaf
    paths: list[list[bytes]] = [[] for _ in leaves]
    level = leaves[:]
    indices = list(range(len(leaves)))

    from eth_utils import keccak

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
            indices.append(indices[-1])

        next_level: list[bytes] = []
        next_indices: list[int] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1]
            left_idx = indices[i]
            right_idx = indices[i + 1]

            parent = keccak(left + right)

            paths[left_idx].append(right)
            if right_idx != left_idx:
                paths[right_idx].append(left)
            else:
                paths[right_idx].append(right)

            next_level.append(parent)
            next_indices.append(left_idx)

        level = next_level
        indices = next_indices

    return level[0], paths
