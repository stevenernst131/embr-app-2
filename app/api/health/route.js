export function GET() {
  console.log(JSON.stringify({ timestamp: new Date().toISOString(), event: "http.request", method: "GET", path: "/api/health" }));
  return Response.json({ status: "healthy" });
}
