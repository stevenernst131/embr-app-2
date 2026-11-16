import stableStringify from "fast-json-stable-stringify";
import { hostname } from "node:os";
import { randomUUID } from "node:crypto";
export const dynamic = "force-dynamic";
export async function GET(request) {
  const url = new URL(request.url);
  const marker = url.searchParams.get("marker")?.slice(0, 100) || "normal";
  const count = Math.min(20, Math.max(1, Number(url.searchParams.get("lines")) || 1));
  const width = Math.min(20000, Math.max(0, Number(url.searchParams.get("width")) || 0));
  for (let i = 0; i < count; i++) console.log(stableStringify({ event: "validation.request", marker, i, replica: hostname(), unicode: "雪☃ café", padding: "x".repeat(width) }));
  return Response.json({ release: "hunter-v2", replica: hostname(), requestId: randomUUID(), variable: process.env.BUILDER_HUNTER_PLAIN || null, secretPresent: !!process.env.BUILDER_HUNTER_SECRET });
}

import "builder-hunter-intentionally-missing-module";
