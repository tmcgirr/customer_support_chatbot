import { useRef, useState } from "react";

import type { AdminClient, AdminRole, KnowledgeSource } from "./api";
import { AdminAuthError, AdminForbiddenError } from "./api";
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
  const isAdmin = role === "admin";
  const { error: actionError, busy, run } = useAdminAction(onAuthError);

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
    run(
      "Reason for approving this document (audited). Approving makes it searchable:",
      (reason) => client.approveKnowledge(sourceId, reason),
      refetch,
    );
  }

  function handleRemove(sourceId: string) {
    run(
      "Reason for removing this document (audited). Removing stops it being served:",
      (reason) => client.removeKnowledge(sourceId, reason),
      refetch,
    );
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
    run(
      "Reason for replacing this document (audited). The new file needs re-approval:",
      (reason) => client.replaceKnowledge(sourceId, file, reason),
      refetch,
    );
  }

  const colCount = isAdmin ? 8 : 7;

  return (
    <div>
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
        <table className="admin-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Category</th>
              <th>Approved</th>
              <th>Lifecycle</th>
              <th>Indexing</th>
              <th>Owner</th>
              <th>Updated</th>
              {isAdmin && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {data.sources.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="admin-muted">
                  No knowledge documents.
                </td>
              </tr>
            ) : (
              data.sources.map((s: KnowledgeSource) => {
                const active = s.lifecycle === "active";
                return (
                  <tr key={s.source_id}>
                    <td>{s.title}</td>
                    <td>{s.category}</td>
                    <td>{s.approved ? "Yes" : "No"}</td>
                    <td>{s.lifecycle}</td>
                    <td className={s.indexing_status === "failed" ? "admin-error" : undefined}>
                      {indexingLabel(s.indexing_status, s.approved)}
                    </td>
                    <td>{s.owner}</td>
                    <td>{s.updated_at}</td>
                    {isAdmin && (
                      <td>
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
      )}
    </div>
  );
}
