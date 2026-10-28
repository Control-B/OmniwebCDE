// Client-only: bundles Monaco and its workers locally instead of loading them from a CDN.
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import CssWorker from 'monaco-editor/language/css/css.worker?worker'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'
import HtmlWorker from 'monaco-editor/language/html/html.worker?worker'
import JsonWorker from 'monaco-editor/language/json/json.worker?worker'
import TsWorker from 'monaco-editor/language/typescript/ts.worker?worker'

self.MonacoEnvironment = {
  getWorker(_id: string, label: string) {
    if (label === 'json') return new JsonWorker()
    if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker()
    if (label === 'html') return new HtmlWorker()
    if (label === 'typescript' || label === 'javascript') return new TsWorker()
    return new EditorWorker()
  },
}

// Generated apps' dependencies live in the sandbox toolchain, not in the browser, so only syntax
// errors are meaningful here. Type errors are reported by the sandboxed type-check instead.
monaco.typescript.typescriptDefaults.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: false })
monaco.typescript.typescriptDefaults.setCompilerOptions({
  jsx: monaco.typescript.JsxEmit.ReactJSX,
  target: monaco.typescript.ScriptTarget.ESNext,
  allowNonTsExtensions: true,
})

monaco.editor.defineTheme('omniweb', {
  base: 'vs-dark',
  inherit: true,
  rules: [],
  colors: { 'editor.background': '#0b0b0c', 'editorGutter.background': '#0b0b0c', 'editor.lineHighlightBackground': '#141415' },
})

loader.config({ monaco })

export { monaco }
