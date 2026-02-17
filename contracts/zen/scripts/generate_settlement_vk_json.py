#!/usr/bin/env python3
"""Generate the SettlementVkJson.sol helper from the cached verifying key JSON."""

from __future__ import annotations

import textwrap
from pathlib import Path


def main() -> None:
    workspace = Path(__file__).resolve().parent.parent
    json_path = workspace / "test/data/settlement_deploy.json"
    output_path = workspace / "test/generated/SettlementVkJson.sol"

    if not json_path.exists():
        raise SystemExit(f"Missing settlement VK JSON at {json_path}")

    raw = json_path.read_bytes()
    hex_payload = raw.hex()
    chunks = textwrap.wrap(hex_payload, 120)
    body = "\n".join(f'        hex"{chunk}"' for chunk in chunks)

    content = (
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity ^0.8.33;\n"
        "\n"
        "/// @notice Auto-generated from test/data/settlement_deploy.json by scripts/generate_settlement_vk_json.py.\n"
        "/// @dev Do not edit manually; update the source JSON instead.\n"
        "library SettlementVkJson {\n"
        "    bytes internal constant SETTLEMENT_VK_JSON =\n"
        f"{body}\n"
        "    ;\n"
        "}\n"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    print(f"Wrote {output_path.relative_to(workspace)} from {json_path.name} ({len(raw)} bytes)")


if __name__ == "__main__":
    main()
