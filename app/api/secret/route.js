import { randomUUID } from "node:crypto";
import { failure, log, secretClient } from "../../../lib/azure";
export const dynamic = "force-dynamic";
export async function GET() {
  const requestId = randomUUID();
  log("http.request", { requestId, method: "GET", path: "/api/secret" });
  try {
    log("azure.keyvault.get.start", { requestId, secretName: process.env.KEY_VAULT_SECRET_NAME });
    const secret = await secretClient().getSecret(process.env.KEY_VAULT_SECRET_NAME);
    log("azure.keyvault.get.success", { requestId, hasValue: !!secret.value });
    return Response.json({ ok: true, hasValue: !!secret.value, requestId });
  } catch (error) {
    failure("azure.keyvault.get.failure", error, requestId);
    return Response.json({ ok: false, requestId, error: error.name, code: error.code }, { status: 502 });
  }
}
