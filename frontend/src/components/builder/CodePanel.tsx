import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, CircleAlert, FileCode2, Folder, Loader2, Save, Undo2 } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useState } from 'react'

import { builder, type FileEntry } from '../../lib/builder'

const Editor = lazy(async () => {
  const [{ default: MonacoEditor }] = await Promise.all([import('@monaco-editor/react'), import('./monaco')])
  return { default: MonacoEditor }
})

const LANGUAGES: Record<string, string> = {
  ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', mjs: 'javascript', json: 'json', css: 'css',
  html: 'html', md: 'markdown', py: 'python', yml: 'yaml', yaml: 'yaml', tf: 'hcl', toml: 'ini', ini: 'ini', txt: 'plaintext',
}

interface TreeNode {
  name: string
  path: string
  file?: FileEntry
  children: TreeNode[]
}

function buildTree(files: FileEntry[]): TreeNode {
  const root: TreeNode = { name: '', path: '', children: [] }
  for (const file of files) {
    let node = root
    const parts = file.path.split('/')
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/')
      let child = node.children.find((c) => c.name === part)
      if (!child) {
        child = { name: part, path, children: [], file: index === parts.length - 1 ? file : undefined }
        node.children.push(child)
      }
      node = child
    })
  }
  const sort = (node: TreeNode) => {
    node.children.sort((a, b) => Number(Boolean(a.file)) - Number(Boolean(b.file)) || a.name.localeCompare(b.name))
    node.children.forEach(sort)
  }
  sort(root)
  return root
}

function useClient() {
  const [ready, setReady] = useState(false)
  useEffect(() => setReady(true), [])
  return ready
}

export function CodePanel({ projectId, headSha, readOnly, busy, openPath, onOpen }: { projectId: string; headSha: string | null; readOnly: boolean; busy: boolean; openPath: string | null; onOpen: (path: string) => void }) {
  const queryClient = useQueryClient()
  const client = useClient()
  const files = useQuery({ queryKey: ['files', projectId, headSha], queryFn: () => builder.files(projectId), enabled: Boolean(headSha) })
  const tree = useMemo(() => buildTree(files.data?.files ?? []), [files.data])
  const [open, setOpen] = useState<Set<string>>(() => new Set(['apps', 'apps/web', 'apps/web/src', 'apps/web/src/pages']))
  const selected = openPath ?? 'apps/web/src/App.tsx'
  const exists = files.data?.files.some((f) => f.path === selected)
  const content = useQuery({ queryKey: ['file', projectId, selected, headSha], queryFn: () => builder.file(projectId, selected), enabled: Boolean(headSha && exists) })
  const [draft, setDraft] = useState<string | null>(null)
  useEffect(() => setDraft(null), [selected, headSha])
  useEffect(() => {
    if (!openPath) return
    const parts = openPath.split('/')
    setOpen((current) => new Set([...current, ...parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/'))]))
  }, [openPath])

  const save = useMutation({
    mutationFn: () => builder.saveFile(projectId, selected, draft ?? ''),
    onSuccess: () => {
      setDraft(null)
      void queryClient.invalidateQueries({ queryKey: ['builder', projectId] })
    },
  })
  const dirty = draft !== null && draft !== content.data?.content
  const file = files.data?.files.find((f) => f.path === selected)

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 's' && dirty && !readOnly && !busy) {
        event.preventDefault()
        save.mutate()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [dirty, readOnly, busy, save])

  if (!headSha) {
    return (
      <div className="st-empty st-empty-panel">
        <FileCode2 size={18} />
        <h3>No source files yet</h3>
        <p className="st-muted">Generate the app and its full source appears here: a React web app, FastAPI service, migrations, tests, and deployment files. All of it is yours to export.</p>
      </div>
    )
  }

  const renderNode = (node: TreeNode, depth: number): React.ReactNode =>
    node.children.map((child) => {
      if (child.file) {
        return (
          <button key={child.path} type="button" className="cp-file" data-active={child.path === selected} style={{ paddingLeft: 10 + depth * 12 }} onClick={() => onOpen(child.path)} title={child.path}>
            <FileCode2 size={13} />
            <span>{child.name}</span>
            {child.file.modified && <i className="cp-dot" title="Edited by hand — Omniweb won't regenerate this file" />}
          </button>
        )
      }
      const isOpen = open.has(child.path)
      return (
        <div key={child.path}>
          <button
            type="button"
            className="cp-dir"
            style={{ paddingLeft: 6 + depth * 12 }}
            aria-expanded={isOpen}
            onClick={() => setOpen((current) => {
              const next = new Set(current)
              if (isOpen) next.delete(child.path)
              else next.add(child.path)
              return next
            })}
          >
            {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <Folder size={13} />
            <span>{child.name}</span>
          </button>
          {isOpen && renderNode(child, depth + 1)}
        </div>
      )
    })

  const extension = selected.split('.').pop() ?? ''
  return (
    <div className="cp">
      <nav className="cp-tree" aria-label="Project files">
        {files.isLoading ? <span className="st-spinner" /> : renderNode(tree, 0)}
      </nav>
      <div className="cp-editor">
        <div className="cp-bar">
          <code title={selected}>{selected}</code>
          {file?.modified && <span className="st-pill st-pill-warn" title="Omniweb keeps your version when it regenerates the app">Edited by you</span>}
          {file && !file.generated && <span className="st-pill">Added by you</span>}
          <div className="cp-bar-actions">
            {dirty && (
              <button type="button" className="bd-icon" onClick={() => setDraft(null)} title="Discard changes"><Undo2 size={14} /></button>
            )}
            {!readOnly && (
              <button type="button" className="lv-btn lv-btn-light cp-save" disabled={!dirty || save.isPending || busy} onClick={() => save.mutate()} title={busy ? 'Wait for the current build' : 'Save, commit, and run checks (Ctrl+S)'}>
                {save.isPending ? <Loader2 size={13} className="bd-spin" /> : <Save size={13} />} Save
              </button>
            )}
          </div>
        </div>
        {save.error && <div className="st-alert st-alert-error cp-alert"><CircleAlert size={14} /> {save.error.message}</div>}
        {!exists && files.data ? (
          <div className="st-empty st-empty-panel"><p className="st-muted">Choose a file to open it.</p></div>
        ) : content.isLoading || !client ? (
          <div className="st-empty st-empty-panel"><span className="st-spinner" /></div>
        ) : content.error ? (
          <div className="st-empty st-empty-panel"><p className="st-muted">{content.error.message}</p></div>
        ) : (
          <Suspense fallback={<div className="st-empty st-empty-panel"><span className="st-spinner" aria-label="Loading editor" /></div>}>
            <Editor
              key={`${selected}:${headSha}`}
              path={selected}
              language={LANGUAGES[extension] ?? 'plaintext'}
              theme="omniweb"
              value={draft ?? content.data?.content ?? ''}
              onChange={(value) => setDraft(value ?? '')}
              options={{ readOnly: readOnly || busy, minimap: { enabled: false }, fontSize: 12.5, fontFamily: "'DM Mono', ui-monospace, monospace", scrollBeyondLastLine: false, tabSize: 2, automaticLayout: true, padding: { top: 10 } }}
            />
          </Suspense>
        )}
      </div>
    </div>
  )
}
