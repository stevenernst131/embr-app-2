# Next.js hybrid

One Next.js component emits both static assets and a standalone SSR server.
The component owns `/` and self-routes pages, dynamic content, and API routes.

```powershell
npm install
npm run build
npm start
```

The production server reads `PORT` and defaults to `3000`.


Validation endpoint: GET /api/validation returns the release marker and replica ID. Optional marker, lines (1-20), and width (0-20000) parameters emit bounded diagnostic logs; no credentials are returned. The endpoint reports only whether the synthetic validation secret exists.
