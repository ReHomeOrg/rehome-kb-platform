/**
 * Layout для /chat/* — Server Component с Nav.
 *
 * Pages в /chat/* — Client Components (нужны useState/useEffect/
 * localStorage/SSE consume). Поэтому Nav (Server Component с next/headers)
 * не может быть импортирован напрямую. Layout фиксит — это Server
 * Component, который монтирует Nav + рендерит children.
 */

import Nav from "@/app/_components/nav";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <>
      <Nav />
      {children}
    </>
  );
}
