import { createFileRoute, Link } from '@tanstack/react-router'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { ArrowLeft, Circle, Command, Maximize2, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import '@xterm/xterm/css/xterm.css'
import { api } from '../lib/api'

export const Route = createFileRoute('/console/$workspaceId')({
  component: WorkspaceConsole,
})

function WorkspaceConsole() {
  const { workspaceId } = Route.useParams()
  const terminalRef = useRef<HTMLDivElement>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!terminalRef.current) return
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: "'DM Mono', ui-monospace, monospace",
      fontSize: 13,
      lineHeight: 1.45,
      theme: { background: '#0d1713', foreground: '#d8e7df', cursor: '#77d1a2', selectionBackground: '#315a47' },
    })
    const fit = new FitAddon()
    terminal.loadAddon(fit)
    terminal.open(terminalRef.current)
    fit.fit()
    terminal.writeln('\x1b[38;5;108mOmniweb secure console\x1b[0m')
    terminal.writeln('\x1b[38;5;244mEstablishing an authenticated workspace session…\x1b[0m\r\n')
    let socket: WebSocket | undefined
    let input = ''
    const prompt = () => terminal.write('\r\n\x1b[38;5;71mdeveloper@omniweb-core\x1b[0m:\x1b[38;5;75m~/project\x1b[0m$ ')
    api.access(workspaceId, 'console')
      .then(({ url }) => {
        const token = new URL(url, window.location.origin).searchParams.get('access_token')
        const apiUrl =
          import.meta.env.VITE_API_URL ??
          (window.location.port === '43210' ? 'http://localhost:8010' : window.location.origin)
        socket = new WebSocket(
          `${apiUrl.replace(/^http/, 'ws')}/api/v1/terminal/${workspaceId}?access_token=${token}`,
        )
        socket.onopen = () => setConnected(true)
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data)
          if (message.type === 'output') terminal.write(message.data)
        }
      })
      .catch(() => {
        setConnected(true)
        terminal.writeln('\x1b[38;5;108mConnected through Coder workspace agent (demo)\x1b[0m')
        terminal.writeln('Ubuntu 24.04.1 LTS · Node 22 · Python 3.12 · Docker 27')
        prompt()
        terminal.onData((data) => {
          if (data === '\r') {
            if (input.trim() === 'ls') terminal.write('\r\nREADME.md  backend  frontend  assets  docker-compose.yml')
            else if (input.trim() === 'git status') terminal.write('\r\nOn branch main\r\nnothing to commit, working tree clean')
            else if (input.trim() === 'codex') terminal.write('\r\n\x1b[38;5;108mCodex CLI ready. Approval mode: on-request\x1b[0m')
            else if (input.trim()) terminal.write(`\r\nbash: ${input.trim()}: command not found`)
            input = ''
            prompt()
          } else if (data === '\u007F') {
            if (input.length) { input = input.slice(0, -1); terminal.write('\b \b') }
          } else {
            input += data
            terminal.write(data)
          }
        })
      })
    const resize = () => { fit.fit(); socket?.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows })) }
    window.addEventListener('resize', resize)
    const dataDisposable = terminal.onData((data) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data }))
    })
    return () => {
      dataDisposable.dispose()
      window.removeEventListener('resize', resize)
      socket?.close()
      terminal.dispose()
    }
  }, [workspaceId])

  return (
    <main className="console-page">
      <header className="console-topbar">
        <Link to="/app"><ArrowLeft size={16} /></Link>
        <div className="console-brand"><Command size={17} /><strong>omniweb</strong><span>/</span><em>omniweb-core</em></div>
        <div className={`connection-state ${connected ? 'online' : ''}`}><Circle size={7} fill="currentColor" />{connected ? 'Connected' : 'Connecting'}</div>
      </header>
      <div className="terminal-tabs">
        <button className="active"><span>Terminal 1</span><X size={13} /></button>
        <button className="new-tab"><Plus size={14} /></button>
        <button className="maximize"><Maximize2 size={14} /></button>
      </div>
      <div ref={terminalRef} className="terminal-surface" />
      <footer className="console-footer"><span>Workspace agent · encrypted transport</span><span>nyc3 · s-4vcpu-8gb</span></footer>
    </main>
  )
}
