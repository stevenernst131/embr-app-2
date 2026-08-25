export const dynamic = "force-dynamic";

export default function DynamicPage() {
  return (
    <main>
      <p className="eyebrow">Server-rendered route</p>
      <h1>Rendered at request time</h1>
      <p>{new Date().toISOString()}</p>
      <a href="/">Return home</a>
    </main>
  );
}

