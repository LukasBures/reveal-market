import type { EventSummary } from "@/lib/api-types";
import { EventCardBinaryYesNo } from "./EventCardBinaryYesNo";
import { EventCardBinary } from "./EventCardBinary";
import { EventCardMultiMarket } from "./EventCardMultiMarket";

type Props = {
  event: EventSummary;
};

const isYesNo = (outcomes: string[] = []) =>
  outcomes.length === 2 && outcomes[0].toLowerCase() === "yes" && outcomes[1].toLowerCase() === "no";

export function EventCard({ event }: Props) {
  const markets = event.markets ?? [];
  if (markets.length > 1) {
    return (
      <div data-testid="event-card">
        <EventCardMultiMarket event={event} />
      </div>
    );
  }
  const market = markets[0];
  const outcomes = market?.outcomes ?? [];
  if (isYesNo(outcomes)) {
    return (
      <div data-testid="event-card">
        <EventCardBinaryYesNo event={event} market={market} />
      </div>
    );
  }
  return (
    <div data-testid="event-card">
      <EventCardBinary event={event} market={market} />
    </div>
  );
}
