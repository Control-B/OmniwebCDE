import { createFileRoute, Link } from '@tanstack/react-router'
import {
  Blocks,
  Bot,
  ChevronDown,
  ChevronRight,
  Code2,
  Files,
  GitBranch,
  Play,
  Search,
  Settings,
  TerminalSquare,
  X,
} from 'lucide-react'
import { useState } from 'react'

export const Route = createFileRoute('/ide/$workspaceId')({
  validateSearch: (search: Record<string, unknown>) => ({
    access_token: typeof search.access_token === 'string' ? search.access_token : '',
  }),
  component: BrowserIde,
})

const files = {
  'README.md': `# Omniweb workspace

Your persistent development environment is ready.

## Quick start

\`\`\`bash
npm install
npm run dev
\`\`\`
`,
  'frontend/src/App.tsx': `import { WorkspaceCard } from './components/WorkspaceCard'

export function App() {
  return (
    <main>
      <h1>Build from anywhere.</h1>
      <WorkspaceCard status="ready" />
    </main>
  )
}
`,
  'backend/main.py': `from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
`,
}

function BrowserIde() {
  const { workspaceId } = Route.useParams()
  const { access_token: token } = Route.useSearch()
  const [activeFile, setActiveFile] = useState<keyof typeof files>('frontend/src/App.tsx')
  const [terminalOpen, setTerminalOpen] = useState(true)
  const content = files[activeFile]

  if (!token) {
    return (
      <main className="ide-denied">
        <h1>IDE session expired</h1>
        <p>Return to the workspace and request a new access session.</p>
        <Link to="/app">Back to Omniweb</Link>
      </main>
    )
  }

  return (
    <main className="browser-ide">
      <header className="ide-titlebar">
        <Link to="/app" className="ide-brand"><Code2 size={17} /> omniweb</Link>
        <span>{activeFile} — workspace</span>
        <div><Play size={14} /><Settings size={14} /></div>
      </header>
      <aside className="ide-rail">
        <button className="active" aria-label="Explorer"><Files size={20} /></button>
        <button aria-label="Search"><Search size={20} /></button>
        <button aria-label="Source control"><GitBranch size={20} /></button>
        <button aria-label="Extensions"><Blocks size={20} /></button>
        <button aria-label="Codex"><Bot size={20} /></button>
      </aside>
      <aside className="ide-explorer">
        <h2>EXPLORER</h2>
        <strong><ChevronDown size={13} /> WORKSPACE</strong>
        {Object.keys(files).map((file) => (
          <button
            key={file}
            className={activeFile === file ? 'active' : ''}
            onClick={() => setActiveFile(file as keyof typeof files)}
          >
            <ChevronRight size={12} />
            <span>{file}</span>
          </button>
        ))}
      </aside>
      <section className="ide-editor">
        <div className="ide-tab"><Code2 size={13} />{activeFile}<X size={12} /></div>
        <pre><code>{content}</code></pre>
        {terminalOpen && (
          <div className="ide-terminal">
            <header><span>TERMINAL</span><button onClick={() => setTerminalOpen(false)}><X size={13} /></button></header>
            <p><em>developer@workspace</em>:<strong>~/project</strong>$ git status</p>
            <p>On branch main</p>
            <p>nothing to commit, working tree clean</p>
            <p><em>developer@workspace</em>:<strong>~/project</strong>$ <i /></p>
          </div>
        )}
      </section>
      <footer className="ide-statusbar">
        <span><GitBranch size={12} /> main</span>
        <span>Workspace {workspaceId.slice(0, 8)} · Agent connected</span>
        {!terminalOpen && <button onClick={() => setTerminalOpen(true)}><TerminalSquare size={12} /> Terminal</button>}
      </footer>
    </main>
  )
}
