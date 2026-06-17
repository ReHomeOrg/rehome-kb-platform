/**
 * Collaborators filters form — native HTML GET submit (#184).
 *
 * Server-side rendered, без client JS. Form reload'ит страницу с query
 * params; SSR re-fetches.
 */

import type { ListCollaboratorsFilters } from "@/lib/api/collaborators";

interface Props {
  initial: ListCollaboratorsFilters;
}

export default function CollaboratorsFilters({ initial }: Props): JSX.Element {
  return (
    <form
      method="get"
      action="/admin/collaborators"
      className="flex flex-wrap items-end gap-2"
      aria-label="Фильтры коллаборантов"
    >
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Тип</span>
        <select
          name="type"
          defaultValue={initial.type ?? ""}
          aria-label="Filter by collaborator type"
          className="w-44 rounded-md border border-gray-300 px-2 py-1 text-xs"
        >
          <option value="">все</option>
          <option value="management_company">management_company</option>
          <option value="emergency_service">emergency_service</option>
          <option value="repair_handyman">repair_handyman</option>
          <option value="cleaning">cleaning</option>
          <option value="moving">moving</option>
          <option value="key_delivery">key_delivery</option>
          <option value="insurance">insurance</option>
          <option value="payment_partner">payment_partner</option>
          <option value="kyc_provider">kyc_provider</option>
          <option value="edo_provider">edo_provider</option>
          <option value="sms_voice">sms_voice</option>
          <option value="it_infrastructure">it_infrastructure</option>
          <option value="legal_consultant">legal_consultant</option>
          <option value="other">other</option>
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Статус</span>
        <select
          name="status"
          defaultValue={initial.status ?? ""}
          aria-label="Filter by status"
          className="w-32 rounded-md border border-gray-300 px-2 py-1 text-xs"
        >
          <option value="">все</option>
          <option value="DRAFT">DRAFT</option>
          <option value="PENDING_REVIEW">PENDING_REVIEW</option>
          <option value="ACTIVE">ACTIVE</option>
          <option value="SUSPENDED">SUSPENDED</option>
          <option value="ARCHIVED">ARCHIVED</option>
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">География</span>
        <input
          type="text"
          name="service_area"
          defaultValue={initial.service_area ?? ""}
          placeholder="например, Москва"
          aria-label="Filter by service area"
          className="w-44 rounded-md border border-gray-300 px-2 py-1 text-xs"
        />
      </label>

      <button
        type="submit"
        className="rounded-md bg-brand px-3 py-1 text-xs font-medium text-white hover:bg-brand-hover"
      >
        Применить
      </button>
    </form>
  );
}
