import type { EventSummary } from "@/lib/api-types";
import { memo } from "react";
import { EventCard } from "./EventCard";

type Props = {
  events: EventSummary[];
};

const MemoizedEventCard = memo(EventCard);

export const EventGrid = memo(function EventGrid({ events }: Props) {
  if (events.length === 0) {
    return null;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {events.map((event) => (
        <MemoizedEventCard key={event.eventId} event={event} />
      ))}
    </div>
  );
});
