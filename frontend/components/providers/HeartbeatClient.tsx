"use client";

import { useEffect } from "react";
import { ensureHeartbeat } from "@/lib/logging";

export function HeartbeatClient() {
  useEffect(() => {
    ensureHeartbeat();
  }, []);

  return null;
}
