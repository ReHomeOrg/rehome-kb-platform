"use client";

/**
 * Список недавних chat-сессий из localStorage.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { getRecentSessions } from "@/lib/chat-storage";

interface RecentMeta {
  id: string;
  created_at: string;
  scope: string;
}

export default function SessionList(): JSX.Element {
  const [sessions, setSessions] = useState<RecentMeta[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setSessions(getRecentSessions());
    setLoaded(true);
  }, []);

  if (!loaded) {
    return <p className="text-sm text-gray-500">Загрузка…</p>;
  }

  if (sessions.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Недавних сессий нет. Создайте первую.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {sessions.map((s) => (
        <li key={s.id} className="rounded-md border border-gray-200 p-3">
          <Link
            href={`/chat/${s.id}`}
            className="text-sm font-medium hover:underline"
          >
            Сессия {s.id.slice(0, 8)}…
          </Link>
          <p className="text-xs text-gray-500">
            {new Date(s.created_at).toLocaleString("ru-RU")} · {s.scope}
          </p>
        </li>
      ))}
    </ul>
  );
}
