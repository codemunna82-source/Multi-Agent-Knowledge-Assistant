import { useEffect, useState } from "react";
import { api } from "./api";
import type { Citation } from "./types";
import { Modal, errText, useLoad } from "./ui";

/** Citation navigation: PDF pages are shown as images with the cited text highlighted (prev/next page); other formats show the stored passage with neighbours. */
export function Preview({ workspace, citation, onClose }: { workspace: string; citation: Citation; onClose: () => void }) {
  const loc = (citation.loc ?? {}) as Record<string, unknown>;
  const startPage = typeof loc.page === "number" ? loc.page : null;
  const [page, setPage] = useState<number | null>(startPage);
  const [img, setImg] = useState<string | null>(null);
  const [text, setText] = useState<{ location: string; text: string; before?: string | null; after?: string | null } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(true);

  useEffect(() => {
    let url: string | null = null;
    let live = true;
    setErr(null);
    (async () => {
      try {
        if (page !== null && citation.source.toLowerCase().endsWith(".pdf")) {
          const b = await api.pageImage(workspace, citation.source_id, page, highlight && page === startPage ? citation.excerpt : undefined);
          url = URL.createObjectURL(b);
          if (live) setImg(url);
        } else if (citation.loc) {
          const p = await api.passage(workspace, citation.source_id, page !== null ? { ...loc, page } : loc);
          if (live) setText(p);
        }
      } catch (e) {
        // a PDF without PyMuPDF (501) or a non-PDF falls back to the stored passage
        try { const p = await api.passage(workspace, citation.source_id, page !== null ? { ...loc, page } : loc); if (live) { setImg(null); setText(p); } } catch { if (live) setErr(errText(e)); }
      }
    })();
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, highlight, citation.source_id]);

  const notes = useLoad(() => (citation.source_id === "web" ? Promise.resolve([]) : api.annotations(workspace, citation.source_id)), [citation.source_id]);
  const [note, setNote] = useState("");
  const [shared, setShared] = useState(false);
  const [nerr, setNerr] = useState<string | null>(null);
  async function addNote(kind: "comment" | "bookmark") {
    try {
      await api.addAnnotation(workspace, { source_id: citation.source_id, loc: page !== null ? { page } : (loc as Record<string, unknown>), quote: citation.excerpt.slice(0, 300) || undefined, note, kind, shared });
      setNote(""); setNerr(null); void notes.reload();
    } catch (e) { setNerr(errText(e)); }
  }

  return (
    <Modal title={`${citation.source} — ${citation.location}`} onClose={onClose}>
      {citation.origin === "web" && <p className="muted small">External web page (not one of your documents): <code>{citation.source}</code></p>}
      <blockquote className="cite">{citation.excerpt}</blockquote>
      {page !== null && (
        <div className="row" role="group" aria-label="Page navigation">
          <button className="small" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹ Page {page - 1}</button>
          <b>Page {page}</b>
          <button className="small" onClick={() => setPage(page + 1)}>Page {page + 1} ›</button>
          <span className="grow" />
          {img && page === startPage && <label className="row small" style={{ margin: 0 }}><input type="checkbox" checked={highlight} onChange={(e) => setHighlight(e.target.checked)} />Highlight cited text</label>}
        </div>
      )}
      {img && <img className="pageimg" src={img} alt={`Page ${page} of ${citation.source}`} />}
      {text && (
        <div className="passage">
          {text.before && <p className="muted small">…{text.before}</p>}
          <p><mark>{text.text}</mark></p>
          {text.after && <p className="muted small">{text.after}…</p>}
        </div>
      )}
      {err && <div className="error" role="alert">{err}</div>}
      {citation.source_id !== "web" && (
        <div className="notes" aria-label="Notes">
          <h3>Notes</h3>
          {(notes.data ?? []).map((n) => (
            <div key={n.id} className="small note"><b>{n.kind}</b>{n.shared ? " · shared" : ""} <code>{JSON.stringify(n.loc)}</code> {n.note}
              {n.mine && <button className="small" aria-label="Delete note" onClick={async () => { await api.deleteAnnotation(n.id); void notes.reload(); }}>×</button>}</div>
          ))}
          <div className="row">
            <input type="text" aria-label="Note" placeholder={`Add a note${page !== null ? ` on page ${page}` : ""}…`} value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1 }} />
            <label className="check small"><input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />share</label>
            <button className="small primary" disabled={!note.trim()} onClick={() => void addNote("comment")}>Add note</button>
            <button className="small" onClick={() => void addNote("bookmark")}>Bookmark</button>
          </div>
          {nerr && <div className="error small" role="alert">{nerr}</div>}
        </div>
      )}
    </Modal>
  );
}
