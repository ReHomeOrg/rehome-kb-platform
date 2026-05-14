import type { Metadata } from "next";
import "./globals.css";

import TokenRefreshScheduler from "./_components/token-refresh-scheduler";

export const metadata: Metadata = {
  title: "reHome — База знаний",
  description: "Платформа базы знаний reHome — модуль help-центра, wiki, документов, AI-чата.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className="antialiased min-h-screen bg-white text-gray-900">
        {/* Pre-emptive auth refresh (#169). No-op для anonymous sessions. */}
        <TokenRefreshScheduler />
        {children}
      </body>
    </html>
  );
}
