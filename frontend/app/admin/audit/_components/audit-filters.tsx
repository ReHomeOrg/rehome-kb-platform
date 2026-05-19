/**
 * Audit log filter form (#166) — native HTML form GET.
 *
 * Server Component-friendly: submit reloads page с query params,
 * SSR re-fetches фильтрованный список. Никакого JS handler'а не нужно.
 */

interface Props {
  initial: {
    actor_sub: string;
    resource_type: string;
    resource_id: string;
    action: string;
    /** Substring search inside metadata JSONB (#183). */
    q: string;
    since: string;
    until: string;
  };
}

export default function AuditFilters({ initial }: Props): JSX.Element {
  return (
    <form
      method="get"
      action="/admin/audit"
      role="search"
      aria-label="Audit log filters"
      className="flex flex-wrap items-end gap-3 rounded-md border border-gray-200 bg-gray-50 p-4"
    >
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Actor (sub)</span>
        <input
          type="text"
          name="actor_sub"
          defaultValue={initial.actor_sub}
          placeholder="UUID или email"
          aria-label="Actor subject identifier"
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Resource type</span>
        <select
          name="resource_type"
          defaultValue={initial.resource_type}
          aria-label="Filter by resource type"
          className="w-32 rounded-md border border-gray-300 px-2 py-1 text-xs"
        >
          <option value="">все</option>
          <option value="article">article</option>
          <option value="collaborator">collaborator</option>
          <option value="document">document</option>
          <option value="premises_card">premises_card</option>
          <option value="hr_employee">hr_employee</option>
          <option value="vault_secret">vault_secret</option>
          <option value="vault_user">vault_user</option>
          <option value="vault_group">vault_group</option>
          <option value="webhook">webhook</option>
          <option value="chat_session">chat_session</option>
          <option value="admin_cache">admin_cache</option>
          <option value="admin_task">admin_task</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Resource ID</span>
        <input
          type="text"
          name="resource_id"
          defaultValue={initial.resource_id}
          placeholder="slug / UUID"
          aria-label="Filter by resource identifier"
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Action</span>
        <input
          type="text"
          name="action"
          defaultValue={initial.action}
          placeholder="articles.created"
          aria-label="Filter by action name"
          className="w-44 rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Поиск в metadata</span>
        <input
          type="search"
          name="q"
          defaultValue={initial.q}
          placeholder="substring (slug / UUID / field)"
          maxLength={200}
          aria-label="Search metadata substring"
          className="w-56 rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">С (ISO)</span>
        <input
          type="datetime-local"
          name="since"
          defaultValue={initial.since}
          aria-label="From datetime (inclusive)"
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">По</span>
        <input
          type="datetime-local"
          name="until"
          defaultValue={initial.until}
          aria-label="Until datetime (exclusive)"
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>
      <button
        type="submit"
        className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
      >
        Применить
      </button>
      <a
        href="/admin/audit"
        aria-label="Reset all filters"
        className="text-xs text-blue-700 underline hover:text-blue-900"
      >
        Сбросить
      </a>
    </form>
  );
}
