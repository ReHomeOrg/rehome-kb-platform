import type { Metadata } from "next";
import "./globals.css";

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
        {children}
      </body>
    </html>
  );
}
