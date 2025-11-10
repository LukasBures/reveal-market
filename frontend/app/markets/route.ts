import { proxyApiRequest } from "@/lib/server/apiProxy";

export async function GET(request: Request) {
  return proxyApiRequest(request, "/markets");
}
