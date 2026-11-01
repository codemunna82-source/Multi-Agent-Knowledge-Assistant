import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { EditorView } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";

/** CodeMirror 6 editor (lazy-loaded). Monaco was not used: it loads its workers from CDNs/blob URLs, which this app's Content-Security-Policy (script-src 'self') forbids, and it is ~5 MB. */
export default function CodeEditor({ value, onChange, language, readOnly = false, label }: { value: string; onChange: (v: string) => void; language: "python" | "javascript"; readOnly?: boolean; label: string }) {
  return (
    <CodeMirror
      value={value} onChange={onChange} readOnly={readOnly} editable={!readOnly} height="auto" minHeight="90px" maxHeight="420px"
      extensions={[language === "python" ? python() : javascript(), EditorView.contentAttributes.of({ "aria-label": label })]}
      basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: !readOnly, autocompletion: false }} theme="none" className="cm-host"
    />
  );
}
