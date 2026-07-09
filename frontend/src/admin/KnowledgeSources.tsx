import { useRef, useState } from "react";

import type { AdminClient, AdminRole, KnowledgeSource } from "./api";
import { AdminAuthError, AdminForbiddenError } from "./api";
import KnowledgeViewer from "./KnowledgeViewer";
import { distinct, FilterSelect, SortHeader, useSort } from "./tableControls";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

/** Human label for the Vector Store ingestion state. An unapproved source is not
 * attached and nothing is ingesting, so it must not read as "Indexing…". */
function indexingLabel(status: string, approved: boolean): string {
  if (status === "failed") return "Failed";
  if (!approved) return "Not indexed";
  if (status === "indexed") return "Indexed";
  if (status === "pending") return "Indexing…";
  return status;
}

const SORT: Record<string, (s: KnowledgeSource) => string | number | null | undefined> = {
  title: (s) => s.title,
  category: (s) => s.category,
  updated_at: (s) => s.updated_at,
};

/** Upload panel (admin only): pick a file + title/category + audit reason. */
function UploadForm({
  onUpload,
  onAuthError,
}: {
  onUpload: (file: File, title: string, category: string, reason: string) => Promise<void>;
  onAuthError: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("general");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Choose a file to upload.");
      return;
    }
    if (!title.trim() || !reason.trim()) {
      setError("Title and reason are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onUpload(file, title.trim(), category.trim() || "general", reason.trim());
      // Reset on success.
      setTitle("");
      setCategory("general");
      setReason("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (err: unknown) {
      if (err instanceof AdminAuthError) {
        onAuthError(); // session died mid-upload → back to login (matches list path)
      } else if (err instanceof AdminForbiddenError) {
        setError("This action requires an admin role.");
      } else {
        setError(err instanceof Error ? err.message : "Upload failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="admin-upload" onSubmit={handleSubmit}>
      <h3>Upload a knowledge document</h3>
      <p className="admin-muted">
        The document is stored but not searchable until you approve it (approve attaches it to the
        knowledge store).
      </p>
      <div className="admin-upload-row">
        <input ref={fileRef} type="file" aria-label="Knowledge file" />
        <input
          type="text"
          placeholder="Title"
          aria-label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          type="text"
          placeholder="Category"
          aria-label="Category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
        <input
          type="text"
          placeholder="Reason (audited)"
          aria-label="Reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <button type="submit" disabled={busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
      {error && <p className="admin-error">{error}</p>}
    </form>
  );
}

export default function KnowledgeSources({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  // Bump to re-fetch after a successful mutation.
  const [reloadNonce, setReloadNonce] = useState(0);
  const [category, setCategory] = useState("");
  const [lifecycle, setLifecycle] = useState("");
  const [approvedFilter, setApprovedFilter] = useState("");
  const [viewing, setViewing] = useState<KnowledgeSource | null>(null);
  const isAdmin = role === "admin";
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  // Hidden file input reused for "Replace"; we stash the target source id.
  const replaceRef = useRef<HTMLInputElement>(null);
  const replaceTarget = useRef<string | null>(null);

  const { data, loading, error } = useAdminQuery(
    () => client.listKnowledgeSources(),
    onAuthError,
    [reloadNonce],
  );

  const refetch = () => setReloadNonce((n) => n + 1);

  async function handleUpload(file: File, title: string, category: string, reason: string) {
    await client.uploadKnowledge(file, title, category, reason);
    refetch();
  }

  function handleApprove(sourceId: string) {
    run({
      title: "Approve document",
      message: "Approve this document? Approving attaches it to the knowledge store and makes it searchable.",
      defaultReason: "Approved document via admin console",
      confirmLabel: "Approve",
      action: (reason) => client.approveKnowledge(sourceId, reason),
      onSuccess: refetch,
    });
  }

  function handleRemove(sourceId: string) {
    run({
      title: "Remove document",
      message: "Remove this document? It stops being served by retrieval.",
      defaultReason: "Removed document via admin console",
      confirmLabel: "Remove",
      danger: true,
      action: (reason) => client.removeKnowledge(sourceId, reason),
      onSuccess: refetch,
    });
  }

  function startReplace(sourceId: string) {
    replaceTarget.current = sourceId;
    replaceRef.current?.click();
  }

  function handleReplaceFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const sourceId = replaceTarget.current;
    // Reset the input so selecting the same file again still fires onChange.
    event.target.value = "";
    replaceTarget.current = null;
    if (!file || !sourceId) return;
    run({
      title: "Replace document",
      message: "Replace this document with the selected file? The new file needs re-approval before it serves.",
      defaultReason: "Replaced document via admin console",
      confirmLabel: "Replace",
      action: (reason) => client.replaceKnowledge(sourceId, file, reason),
      onSuccess: refetch,
    });
  }

  const colCount = isAdmin ? 8 : 7;

  const all = data?.sources ?? [];
  const filtered = all.filter(
    (s) =>
      (!category || s.category === category) &&
      (!lifecycle || s.lifecycle === lifecycle) &&
      (!approvedFilter || (s.approved ? "Yes" : "No") === approvedFilter),
  );
  const { sorted, sort, toggle } = useSort(filtered, SORT, { key: "updated_at", dir: "desc" });

  return (
    <div>
      {dialog}
      {viewing && (
        <KnowledgeViewer
          client={client}
          source={viewing}
          onClose={() => setViewing(null)}
          onAuthError={onAuthError}
        />
      )}
      {isAdmin && <UploadForm onUpload={handleUpload} onAuthError={onAuthError} />}
      {/* Hidden input driving per-row "Replace". */}
      <input
        ref={replaceRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleReplaceFile}
      />
      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading knowledge documents…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <>
          <div className="admin-filters">
            <FilterSelect
              label="Category"
              value={category}
              options={distinct(all, (s) => s.category)}
              onChange={setCategory}
            />
            <FilterSelect
              label="Lifecycle"
              value={lifecycle}
              options={distinct(all, (s) => s.lifecycle)}
              onChange={setLifecycle}
            />
            <FilterSelect
              label="Approved"
              value={approvedFilter}
              options={["Yes", "No"]}
              onChange={setApprovedFilter}
            />
            <span className="admin-muted">
              {sorted.length} of {all.length}
            </span>
          </div>

          <div className="admin-tablewrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <SortHeader label="Title" sortKey="title" sort={sort} onToggle={toggle} />
                  <SortHeader label="Category" sortKey="category" sort={sort} onToggle={toggle} />
                  <th>Approved</th>
                  <th>Lifecycle</th>
                  <th>Indexing</th>
                  <th>Owner</th>
                  <SortHeader label="Updated" sortKey="updated_at" sort={sort} onToggle={toggle} />
                  {isAdmin && <th className="admin-col-sticky">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 ? (
                  <tr>
                    <td colSpan={colCount} className="admin-muted">
                      No knowledge documents.
                    </td>
                  </tr>
                ) : (
                  sorted.map((s: KnowledgeSource) => {
                const active = s.lifecycle === "active";
                return (
                  <tr key={s.source_id}>
                    <td>
                      <button
                        type="button"
                        className="admin-link"
                        title="View document"
                        onClick={() => setViewing(s)}
                      >
                        {s.title}
                      </button>
                    </td>
                    <td>{s.category}</td>
                    <td>{s.approved ? "Yes" : "No"}</td>
                    <td>{s.lifecycle}</td>
                    <td className={s.indexing_status === "failed" ? "admin-error" : undefined}>
                      {indexingLabel(s.indexing_status, s.approved)}
                    </td>
                    <td>{s.owner}</td>
                    <td>{s.updated_at}</td>
                    {isAdmin && (
                      <td className="admin-col-sticky">
                        {active && !s.approved && (
                          <button
                            type="button"
                            className="admin-link"
                            disabled={busy}
                            onClick={() => handleApprove(s.source_id)}
                          >
                            Approve
                          </button>
                        )}
                        {active && (
                          <button
                            type="button"
                            className="admin-link"
                            disabled={busy}
                            onClick={() => startReplace(s.source_id)}
                          >
                            Replace
                          </button>
                        )}
                        {s.lifecycle !== "removed" && (
                          <button
                            type="button"
                            className="admin-link"
                            disabled={busy}
                            onClick={() => handleRemove(s.source_id)}
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
