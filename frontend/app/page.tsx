import { Hero } from "@/components/marketing/Hero";
import { MarketsSection } from "@/components/marketing/MarketsSection";
import { CTASection } from "@/components/marketing/CTASection";

export default function HomePage() {
  return (
    <>
      <Hero />
      <MarketsSection />
      <div className="px-4 py-16">
        <CTASection />
      </div>
    </>
  );
}
