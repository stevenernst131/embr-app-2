import { randomUUID } from "node:crypto";
import { failure, itemsContainer, log } from "../../../lib/azure";
export const dynamic = "force-dynamic";
export async function GET() {
  const requestId = randomUUID();
  log("http.request", { requestId, method: "GET", path: "/api/items" });
  try {
    log("azure.cosmos.list.start", { requestId });
    const { resources } = await itemsContainer().items.query("SELECT TOP 10 c.id, c.category, c.createdAt FROM c ORDER BY c.createdAt DESC").fetchAll();
    log("azure.cosmos.list.success", { requestId, count: resources.length });
    return Response.json({ ok: true, items: resources, requestId });
  } catch (error) {
    failure("azure.cosmos.list.failure", error, requestId);
    return Response.json({ ok: false, requestId, error: error.name, code: error.code }, { status: 502 });
  }
}
export async function POST() {
  const requestId = randomUUID();
  log("http.request", { requestId, method: "POST", path: "/api/items" });
  try {
    log("azure.cosmos.create.start", { requestId });
    const item = { id: randomUUID(), category: "validation", createdAt: new Date().toISOString() };
    await itemsContainer().items.create(item);
    log("azure.cosmos.create.success", { requestId, itemId: item.id });
    return Response.json({ ok: true, item, requestId }, { status: 201 });
  } catch (error) {
    failure("azure.cosmos.create.failure", error, requestId);
    return Response.json({ ok: false, requestId, error: error.name, code: error.code }, { status: 502 });
  }
}
