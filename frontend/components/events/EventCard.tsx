import type { EventSummary } from "@/lib/api-types";
import { EventCardBinaryGauge } from "./EventCardBinaryGauge";
import { EventCardHeadToHead } from "./EventCardHeadToHead";
import { EventCardMultiOutcome } from "./EventCardMultiOutcome";

type Props = {
  event: EventSummary;
};

const isYesNo = (outcomes: string[] = []) =>
  outcomes.length === 2 && outcomes[0].toLowerCase() === "yes" && outcomes[1].toLowerCase() === "no";

const getPrimaryHeadToHeadMarket = (event: EventSummary) => {
  if (event.category?.toLowerCase() !== "sports") {
    return undefined;
  }
  return (event.markets ?? []).find((market) => {
    const outcomes = market.outcomes ?? [];
    return outcomes.length === 2 && !isYesNo(outcomes);
  });
};

export function EventCard({ event }: Props) {
  const markets = event.markets ?? [];
  const market = markets[0];
  const outcomes = market?.outcomes ?? [];
  const isBinary = markets.length === 1 && outcomes.length === 2;

  if (isBinary && isYesNo(outcomes)) {
    return (
      <div data-testid="event-card">
        <EventCardBinaryGauge event={event} market={market} />
      </div>
    );
  }

  if (isBinary) {
    return (
      <div data-testid="event-card">
        <EventCardHeadToHead event={event} market={market} />
      </div>
    );
  }

  const primaryHeadToHead = getPrimaryHeadToHeadMarket(event);
  if (primaryHeadToHead) {
    return (
      <div data-testid="event-card" className="h-full">
        <EventCardHeadToHead event={event} market={primaryHeadToHead} />
      </div>
    );
  }

  return (
    <div data-testid="event-card" className="h-full">
      <EventCardMultiOutcome event={event} />
    </div>
  );
}
