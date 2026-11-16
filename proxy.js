import { NextResponse } from "next/server";

export function proxy(request) {
  console.log(JSON.stringify({ timestamp: new Date().toISOString(), event: "http.received", method: request.method, path: request.nextUrl.pathname }));
  return NextResponse.next();
}
