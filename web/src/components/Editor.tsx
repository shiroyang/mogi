// CodeMirror 6 wrapper: Python, a theme on the app's tokens, ⌘↩ run / ⇧⌘↩ submit.
// Bundled with the app (no CDN), light, and usable with a touch keyboard.
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { bracketMatching, HighlightStyle, indentOnInput, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { EditorState, Prec } from "@codemirror/state";
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export interface EditorHandle { getValue(): string; setValue(v: string): void; focus(): void }
interface Props { initial: string; onChange?: (v: string) => void; onRun?: () => void; onSubmit?: () => void; className?: string }

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "13.5px", backgroundColor: "transparent", color: "var(--ink)" },
  ".cm-scroller": { fontFamily: "var(--mono)", lineHeight: "1.55", overflow: "auto" },
  ".cm-content": { padding: "10px 0", caretColor: "var(--aqua-2)" },
  ".cm-gutters": { backgroundColor: "transparent", color: "rgba(238,243,248,.3)", border: "none", paddingLeft: "6px" },
  ".cm-activeLineGutter": { backgroundColor: "rgba(255,255,255,.04)", color: "rgba(238,243,248,.6)" },
  ".cm-activeLine": { backgroundColor: "rgba(255,255,255,.035)" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--aqua-2)", borderLeftWidth: "2px" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": { backgroundColor: "rgba(88,199,212,.28) !important" },
  ".cm-matchingBracket": { backgroundColor: "rgba(88,199,212,.22)", outline: "1px solid rgba(88,199,212,.5)" },
  "&.cm-focused": { outline: "none" },
  "@media (max-width: 899px)": { "&": { fontSize: "14px" } },
}, { dark: true });

const highlight = HighlightStyle.define([
  { tag: t.keyword, color: "#b8a3ff" },
  { tag: [t.controlKeyword, t.operatorKeyword], color: "#c9b8ff" },
  { tag: [t.string, t.special(t.string)], color: "#9ad8a7" },
  { tag: [t.number, t.bool, t.null], color: "#f0b545" },
  { tag: t.comment, color: "rgba(238,243,248,.42)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.function(t.definition(t.variableName))], color: "#7fd8e6" },
  { tag: [t.definition(t.variableName), t.definition(t.className)], color: "#eef3f8", fontWeight: "600" },
  { tag: [t.className, t.typeName], color: "#f6c177" },
  { tag: [t.standard(t.variableName), t.self], color: "#58c7d4" },
  { tag: t.operator, color: "#d8e0ea" },
  { tag: t.punctuation, color: "rgba(238,243,248,.7)" },
  { tag: t.propertyName, color: "#dbe6f0" },
]);

export const Editor = forwardRef<EditorHandle, Props>(function Editor({ initial, onChange, onRun, onSubmit, className }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const cb = useRef({ onChange, onRun, onSubmit });
  cb.current = { onChange, onRun, onSubmit };

  useEffect(() => {
    const state = EditorState.create({
      doc: initial,
      extensions: [
        lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(), drawSelection(), history(),
        bracketMatching(), indentOnInput(), indentUnit.of("    "), EditorState.tabSize.of(4),
        python(), syntaxHighlighting(highlight), theme,
        Prec.highest(keymap.of([
          { key: "Mod-Enter", run: () => { cb.current.onRun?.(); return true; } },
          { key: "Shift-Mod-Enter", run: () => { cb.current.onSubmit?.(); return true; } },
        ])),
        keymap.of([indentWithTab, ...defaultKeymap, ...historyKeymap]),
        EditorView.updateListener.of(u => { if (u.docChanged) cb.current.onChange?.(u.state.doc.toString()); }),
      ],
    });
    view.current = new EditorView({ state, parent: host.current! });
    return () => { view.current?.destroy(); view.current = null; };
    // the editor owns its document after mount; `initial` is only the seed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useImperativeHandle(ref, () => ({
    getValue: () => view.current?.state.doc.toString() ?? "",
    setValue: (v: string) => {
      const vw = view.current; if (!vw) return;
      vw.dispatch({ changes: { from: 0, to: vw.state.doc.length, insert: v } });
    },
    focus: () => view.current?.focus(),
  }), []);

  return <div ref={host} className={`editor ${className || ""}`} />;
});
