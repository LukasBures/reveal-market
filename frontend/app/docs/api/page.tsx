import Link from "next/link";
import { Code } from "@/components/docs/primitives";

const endpoints = [
  {
    title: "GET /markets",
    description: "Query markets with pagination + filters.",
    example: `curl "$RM_API_BASE_URL/markets?limit=10&status=open"`,
  },
  {
    title: "GET /markets/{event_id}",
    description: "Fetch details for a specific market by event ID.",
    example: `curl "$RM_API_BASE_URL/markets/olympics-2024"`,
  },
  {
    title: "GET /resolution/{condition}",
    description: "Fetch resolution metadata by Conditional Tokens condition ID.",
    example: `curl "$RM_API_BASE_URL/resolution/0xconditionid"`,
  },
];

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
      <div className="space-y-6">
        {endpoints.map((endpoint) => (
          <section key={endpoint.title}>
            <h2 className="text-xl font-semibold text-white">{endpoint.title}</h2>
            <p>{endpoint.description}</p>
            <Code>{endpoint.example}</Code>
          </section>
        ))}
      </div>
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
        Mutation endpoints (POST/PATCH) are protected and used by the worker or
        internal dashboards. See{" "}
        <Code inline>backend/api/app/routes</Code> for the schema, and refer to the
        `backend/TODO.md` for upcoming API expansions.
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <span>Next:</span>
        <Link
          href="/docs/integrations"
          className="rounded-full border border-white/20 px-3 py-1 text-white hover:bg-white/10"
        >
          Integrations
        </Link>
      </div>
    </>
  );
}
