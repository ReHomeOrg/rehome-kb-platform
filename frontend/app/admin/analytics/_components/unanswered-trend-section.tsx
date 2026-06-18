import Link from "next/link";

import type { UnansweredTrendResponse } from "@/lib/api/admin-analytics";

interface Props {
  data: UnansweredTrendResponse["data"];
  windowHours: number;
}

const HOT_THRESHOLD = 5;

const dateFmt = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export default function UnansweredTrendSection({
  data,
  windowHours,
}: Props): JSX.Element {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          Топ необработанных chat-запросов
        </h2>
        <Link
          href="/admin/chat-unanswered-queries?status=NEW"
          className="text-sm text-brand-strong hover:underline"
        >
          Очередь модерации →
        </Link>
      </div>
      {data.length === 0 ? (
        <p className="rounded-md border border-gray-200 bg-white p-4 text-sm text-gray-600">
          Нет необработанных запросов за выбранный период (window=
          {windowHours} ч).
        </p>
      ) : (
        <table className="w-full overflow-hidden rounded-md border border-gray-200 bg-white text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-600">
            <tr>
              <th className="px-3 py-2">Запрос (нормализованный)</th>
              <th className="px-3 py-2 text-right">Повторов</th>
              <th className="px-3 py-2 text-right">Первый</th>
              <th className="px-3 py-2 text-right">Последний</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => {
              const hot = row.count >= HOT_THRESHOLD;
              return (
                <tr
                  key={row.normalized_query}
                  className="border-t border-gray-100 even:bg-gray-50/30"
                >
                  <td className="px-3 py-2 font-mono text-xs text-gray-800">
                    {row.normalized_query}
                  </td>
                  <td
                    className={`px-3 py-2 text-right ${hot ? "font-medium text-red-700" : "text-gray-700"}`}
                  >
                    {row.count}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {dateFmt.format(new Date(row.first_seen))}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-700">
                    {dateFmt.format(new Date(row.last_seen))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="text-xs text-gray-500">
        Группировка по lower(query_masked); подсвечены запросы с 5+ повторами.
        Детальный разбор и attach к статьям — в очереди модерации.
      </p>
    </section>
  );
}
