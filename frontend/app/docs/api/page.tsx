import { Code } from "@/components/docs/primitives";

export default function ApiReferencePage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Docs · API
      </p>
      <h1 className="text-3xl font-semibold text-white">API Reference</h1>
      <p>
        The FastAPI service exposes JSON endpoints secured by rate limits. Use
        the base URL configured via <Code inline>RM_API_BASE_URL</Code> /
        <Code inline>NEXT_PUBLIC_API_BASE_URL</Code>.
      </p>
      <h2 className="text-xl font-semibold text-white">GET /markets</h2>
      <p>Query markets with pagination + filters.</p>
      <Code>{`curl "$RM_API_BASE_URL/markets?limit=10&status=open"`}</Code>
      <h2 className="text-xl font-semibold text-white">
        GET /markets/{`{event_id}`}
      </h2>
      <Code>{`curl "$RM_API_BASE_URL/markets/olympics-2024"`}</Code>
      <h2 className="text-xl font-semibold text-white">GET /resolution</h2>
      <Code>{`curl "$RM_API_BASE_URL/resolution/0xconditionid"`}</Code>
      <p>
        Mutation endpoints (POST/PATCH) are protected and used by the worker +
        operations dashboard. See{" "}
        <Code inline>backend/api/app/routes</Code> for the full schema.
      </p>
    </>
  );
}
