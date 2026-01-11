import { redirect } from "next/navigation";

export default function LegacyMarketsSearchRedirect() {
  redirect("/search");
}
