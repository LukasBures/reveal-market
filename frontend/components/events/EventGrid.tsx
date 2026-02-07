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
    <div className="grid auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3">
      {events.map((event, index) => {
        const priorityEvent = index < PRIORITY_COUNT && event.eventId;
        const eventId = priorityEvent ? `${event.eventId}-p` : event.eventId;
        return <MemoizedEventCard key={eventId} event={{ ...event, eventId }} />;
      })}
    </div>
  );
});
