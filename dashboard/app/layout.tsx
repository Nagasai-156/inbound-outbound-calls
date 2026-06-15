import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Voice Calls — Console",
  description: "Realtime multilingual AI voice calling — admin console",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
