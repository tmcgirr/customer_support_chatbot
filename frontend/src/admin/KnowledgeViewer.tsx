import { useEffect } from "react";

import type { AdminClient, KnowledgeSource } from "./api";
import { useAdminQuery } from "./useAdminQuery";

/** Read-only viewer for a knowledge document's stored text (both roles). */
export default function KnowledgeViewer({
  client,
  source,
  onClose,
  onAuthError,
}: {
  client: AdminClient;
  source: KnowledgeSource;
  onClose: () => void;
  onAuthError: () => void;
}) {
  const { data, loading, error } = useAdminQuery(
    () => client.getKnowledgeContent(source.source_id),
    onAuthError,
    [source.source_id],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="admin-modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="admin-modal admin-modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label={`Document: ${source.title}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="admin-modal-head">
          <h3 className="admin-modal-title">{source.title}</h3>
          <button
            type="button"
            className="admin-btn admin-btn-ghost admin-btn-sm"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <p className="admin-modal-message">
          {source.category} · {source.approved ? "approved" : "not approved"} · {source.lifecycle}{" "}
          · updated {source.updated_at}
        </p>

        {loading ? (
          <p className="admin-muted">Loading document…</p>
        ) : error ? (
          <p className="admin-error">{error}</p>
        ) : !data?.available ? (
          <p className="admin-muted">
            No text preview available — this document may be a binary/PDF upload, or was added
            before previews were stored.
          </p>
        ) : (
          <pre className="admin-doc-content">{data.content}</pre>
        )}
      </div>
    </div>
  );
}
