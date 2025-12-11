import { render } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HeartbeatClient } from "@/components/providers/HeartbeatClient";

const ensureHeartbeatMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/logging", () => ({
  ensureHeartbeat: ensureHeartbeatMock,
}));

describe("HeartbeatClient", () => {
  beforeEach(() => {
    ensureHeartbeatMock.mockReset();
  });

  it("triggers ensureHeartbeat on mount", () => {
    render(<HeartbeatClient />);
    expect(ensureHeartbeatMock).toHaveBeenCalledTimes(1);
  });
});
