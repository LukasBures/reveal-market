"use client";

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
    return <EventCardMultiMarket event={event} />;
  }
  const market = markets[0];
  const outcomes = market?.outcomes ?? [];
  if (isYesNo(outcomes)) {
    return <EventCardBinaryYesNo event={event} market={market} />;
  }
  return <EventCardBinary event={event} market={market} />;
}
