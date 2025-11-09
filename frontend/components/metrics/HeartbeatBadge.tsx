import { fetchHealthSnapshot } from "@/lib/api";

export async function HeartbeatBadge() {
  const health = await fetchHealthSnapshot();
  const heartbeat = health?.workerHeartbeat;
  if (!heartbeat) {
    return null;
  }

  return (
    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/50 px-3 py-1 text-xs text-slate-300">
      <span className="inline-flex h-2 w-2 rounded-full bg-green-400" aria-hidden />
      Last sync{" "}
      <span className="font-semibold text-white">
        {heartbeat.timestamp ? new Date(heartbeat.timestamp).toLocaleString() : "unknown"}
      </span>
      {typeof heartbeat.latencyMs === "number" && (
        <span className="text-slate-500">({Math.round(heartbeat.latencyMs)} ms)</span>
      )}
    </div>
  );
}
