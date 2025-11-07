export default function ArchitecturePage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Platform
      </p>
      <h1 className="text-3xl font-semibold text-white">Architecture</h1>
      <p>
        The Reveal Platform was engineered to satisfy institutional diligence:
        segregated services, deterministic settlement, and observability
        throughout the stack. Rather than expose repository details, here is the
        investor-facing blueprint.
      </p>
      <div className="mt-6 space-y-4">
        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">Zero-Kernel Core</h2>
          <p className="text-slate-200">
            zk-enabled smart contracts enforce commit/reveal logic, guardian
            controls, and fee splits. Audited factories can deploy branded
            markets in minutes while retaining protocol security guarantees.
          </p>
        </section>
        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">Enterprise Fabric</h2>
          <p className="text-slate-200">
            API surface, ingestion services, and analytics pipelines keep
            institutional partners in sync with on-chain state. Everything ships
            with metrics, alerting, and compliance-grade logging.
          </p>
        </section>
        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">Experience Layer</h2>
          <p className="text-slate-200">
            White-label marketplace modules, wallet-ready UX, and partner SDKs
            let exchanges and media brands launch their own Reveal-powered
            surfaces without touching low-level infrastructure.
          </p>
        </section>
      </div>
      <p className="mt-6 text-slate-200">
        This architecture keeps alpha private, settlements verifiable, and the
        partner experience turnkey—exactly what sophisticated investors require
        to scale exposure.
      </p>
    </>
  );
}
