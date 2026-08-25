import "./globals.css";

export const metadata = {
  title: "Next.js hybrid sample",
  description: "An Embr hybrid builder sample"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

