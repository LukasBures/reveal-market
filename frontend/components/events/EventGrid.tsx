import type { EventSummary } from "@/lib/api-types";
import { memo } from "react";
import { EventCard } from "./EventCard";

type Props = {
  events: EventSummary[];
};

const MemoizedEventCard = memo(EventCard);
const PRIORITY_COUNT = 6;

export const EventGrid = memo(function EventGrid({ events }: Props) {
  if (events.length === 0) {
    return null;
  }
  return (
    <div className="grid grid-cols-1 auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3">
      {events.map((event, index) => {
        const isPriority = index < PRIORITY_COUNT;
        return <MemoizedEventCard key={event.eventId} event={event} priority={isPriority} />;
      })}
    </div>
  );
});
