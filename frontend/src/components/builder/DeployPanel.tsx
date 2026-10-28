import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownToLine, ArrowUpFromLine, CircleAlert, Cloud, ExternalLink, GitBranch, Loader2, RotateCcw, Rocket, Terminal } from 'lucide-react'
import { useState } from 'react'

import { api, ApiError } from '../../lib/api'
import { builder, type BuilderState } from '../../lib/builder'

const REGIONS = [
  ['nyc', 'New York'], ['sfo', 'San Francisco'], ['tor', 'Toronto'], ['ams', 'Amsterdam'], ['lon', 'London'], ['fra', 'Frankfurt'], ['sgp', 'Singapore'], ['blr', 'Bangalore'], ['syd', 'Sydney'],
] as const

const STATUS: Record<string, string> = {
  awaiting_approval: 'Waiting for approval',
  deploying: 'Deploying',
  live: 'Live',
  superseded: 'Replaced',
  failed: 'Failed',
  rejected: 'Rejected',
}

export function DeployPanel({ projectId, projectName, state, readOnly }: { projectId: string; projectName: string; state: BuilderState | undefined; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const refresh = () => {
    for (const key of ['github', 'deployments', 'builder']) void queryClient.invalidateQueries({ queryKey: [key, projectId] })
  }
  const github = useQuery({ queryKey: ['github', projectId, state?.head_sha], queryFn: () => builder.github(projectId), enabled: Boolean(state) })
  const deployments = useQuery({ queryKey: ['deployments', projectId], queryFn: () => builder.deployments(projectId), refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'deploying') ? 3000 : false) })
  const connections = useQuery({ queryKey: ['connections'], queryFn: () => api.connections() })
  const [repo, setRepo] = useState('')
  const [branch, setBranch] = useState('main')
  const [installation, setInstallation] = useState('')
  const [environment, setEnvironment] = useState<'development' | 'production'>('development')
  const [region, setRegion] = useState('nyc')
  const [connection, setConnection] = useState('')

  const connect = useMutation({ mutationFn: () => builder.connectGithub(projectId, repo.trim(), branch.trim(), installation.trim()), onSuccess: refresh })
  const push = useMutation({ mutationFn: () => builder.push(projectId), onSuccess: refresh })
  const pull = useMutation({ mutationFn: () => builder.pull(projectId), onSuccess: refresh })
  const estimate = useQuery({ queryKey: ['estimate', projectId, environment, region, state?.spec?.targets.join()], queryFn: () => builder.estimate(projectId, environment, region), enabled: Boolean(state?.spec) })
  const deploy = useMutation({ mutationFn: () => builder.deploy(projectId, environment, region, connection || undefined), onSuccess: refresh })
  const rollback = useMutation({ mutationFn: (id: string) => builder.rollback(projectId, id), onSuccess: refresh })

  if (!state?.head_sha) {
    return (
      <div className="st-empty st-empty-panel">
        <Rocket size={18} />
        <h3>Nothing to ship yet</h3>
        <p className="st-muted">Generate the app first. Then you can sync it to GitHub, open it in a cloud workspace, and deploy it to DigitalOcean App Platform with an approval step.</p>
      </div>
    )
  }

  const g = github.data
  const built = Boolean(state.last_build?.ok && state.last_build.sha === state.head_sha)
  const pushed = Boolean(g?.repo && g.last_pushed_sha === state.head_sha)
  const conflicts = pull.error instanceof ApiError ? pull.error.conflicts : []

  return (
    <div className="st-scroll dp">
      <section className="dp-section">
        <h4 className="st-h4"><GitBranch size={12} /> GitHub</h4>
        {!g?.repo ? (
          readOnly ? <p className="st-muted">No repository connected.</p> : (
            <form className="st-form" onSubmit={(e) => { e.preventDefault(); if (repo.trim()) connect.mutate() }}>
              <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/repository" aria-label="Repository" spellCheck={false} />
              <div className="dp-pair">
                <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" aria-label="Branch" spellCheck={false} />
                {g?.mode === 'github' && <input value={installation} onChange={(e) => setInstallation(e.target.value)} placeholder="App installation ID" aria-label="GitHub App installation ID" inputMode="numeric" />}
              </div>
              <button type="submit" className="lv-btn lv-btn-light" disabled={!repo.trim() || connect.isPending}>{connect.isPending && <Loader2 size={13} className="bd-spin" />} Connect repository</button>
              {connect.error && <p className="st-error">{connect.error.message}</p>}
              <p className="st-fine">
                {g?.mode === 'github'
                  ? 'Install the Omniweb GitHub App on the repository first. Omniweb uses short-lived installation tokens and never stores a personal access token.'
                  : 'No GitHub App is configured on this server, so Omniweb syncs with a local repository that stands in for GitHub. Set OMNIWEB_GITHUB_APP_ID and OMNIWEB_GITHUB_APP_PRIVATE_KEY to sync with github.com.'}
              </p>
            </form>
          )
        ) : (
          <>
            <div className="st-kv"><span>Repository</span><strong>{g.repo}{g.mode === 'local' && <span className="st-pill dp-mock">local stand-in</span>}</strong></div>
            <div className="st-kv"><span>Branch</span><strong><code>{g.branch}</code></strong></div>
            <div className="st-kv"><span>Status</span><strong>{g.error ? <span className="st-error">{g.error}</span> : g.remote_sha === undefined ? '…' : !g.remote_sha ? 'Not pushed yet' : g.ahead === 0 && g.behind === 0 ? 'In sync' : `${g.ahead} to push · ${g.behind} to pull`}</strong></div>
            {!readOnly && (
              <div className="st-row dp-buttons">
                <button type="button" className="lv-btn lv-btn-light" disabled={push.isPending || state.active || (g.ahead === 0 && Boolean(g.remote_sha))} onClick={() => push.mutate()}>{push.isPending ? <Loader2 size={13} className="bd-spin" /> : <ArrowUpFromLine size={13} />} Push</button>
                <button type="button" className="lv-btn lv-btn-ghost" disabled={pull.isPending || state.active || !g.behind} onClick={() => pull.mutate()}>{pull.isPending ? <Loader2 size={13} className="bd-spin" /> : <ArrowDownToLine size={13} />} Pull</button>
              </div>
            )}
            {push.error && <div className="st-alert st-alert-error"><CircleAlert size={14} /> {push.error.message}</div>}
            {pull.error && (
              <div className="st-alert st-alert-error">
                <CircleAlert size={14} />
                <div>{pull.error.message}{conflicts.length > 0 && <ul className="dp-conflicts">{conflicts.map((f) => <li key={f}><code>{f}</code></li>)}</ul>}</div>
              </div>
            )}
            {pull.data && <p className="st-ok">{pull.data.message}</p>}
            <div className="dp-clone">
              <p className="st-fine"><Terminal size={11} /> Open it in a cloud workspace or locally:</p>
              <code>git clone {g.clone_url}</code>
            </div>
          </>
        )}
      </section>

      <section className="dp-section">
        <h4 className="st-h4"><Cloud size={12} /> DigitalOcean App Platform</h4>
        <div className="dp-pair">
          <label className="st-field">Environment
            <select value={environment} onChange={(e) => setEnvironment(e.target.value as 'development' | 'production')}>
              <option value="development">Development</option>
              <option value="production">Production</option>
            </select>
          </label>
          <label className="st-field">Region
            <select value={region} onChange={(e) => setRegion(e.target.value)}>
              {REGIONS.map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}
            </select>
          </label>
        </div>
        {connections.data && connections.data.length > 1 && (
          <label className="st-field">Account
            <select value={connection} onChange={(e) => setConnection(e.target.value)}>
              <option value="">{connections.data[0].label}</option>
              {connections.data.slice(1).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </label>
        )}
        {estimate.data && (
          <div className="dp-estimate">
            {estimate.data.lines.map((line) => <div key={line.item} className="st-kv"><span>{line.item}</span><strong>${line.monthly_usd.toFixed(2)}/mo</strong></div>)}
            <div className="st-kv dp-total"><span>Estimated total</span><strong>${estimate.data.monthly_usd.toFixed(2)}/mo</strong></div>
            <p className="st-fine">{estimate.data.note}</p>
          </div>
        )}
        <ul className="dp-checklist">
          <li data-ok={built}>{built ? 'Latest commit passed its checks' : 'The latest commit must pass its checks'}</li>
          <li data-ok={pushed}>{pushed ? 'Latest commit is on GitHub' : 'Push the latest commit — App Platform builds from GitHub'}</li>
          <li data-ok={Boolean(connections.data?.length)}>{connections.data?.length ? `DigitalOcean account: ${connections.data[0].label}` : 'Connect a DigitalOcean account in Workspaces → Cloud accounts'}</li>
        </ul>
        {!readOnly && (
          <button type="button" className="lv-btn lv-btn-light st-wide" disabled={!built || !pushed || !connections.data?.length || deploy.isPending} onClick={() => deploy.mutate()}>
            {deploy.isPending ? <Loader2 size={13} className="bd-spin" /> : <Rocket size={13} />} Request {environment} deployment
          </button>
        )}
        {deploy.error && <div className="st-alert st-alert-error"><CircleAlert size={14} /> {deploy.error.message}</div>}
        <p className="st-fine">Nothing is created until someone approves the request. Production needs the project owner to type <code>{projectName}</code>. Agents can't deploy on their own.</p>
      </section>

      {deployments.data && deployments.data.length > 0 && (
        <section className="dp-section">
          <h4 className="st-h4">History</h4>
          <ol className="dp-history">
            {deployments.data.map((d) => (
              <li key={d.id} data-status={d.status}>
                <div className="dp-history-head">
                  <strong>{d.rollback_of ? 'Rollback' : 'Deploy'} <code>{d.commit_sha.slice(0, 7)}</code> → {d.environment}</strong>
                  <span className={`st-pill${d.status === 'live' ? ' st-pill-ok' : d.status === 'failed' ? ' st-pill-warn' : ''}`}>{STATUS[d.status] ?? d.status}</span>
                </div>
                <small>{d.region.toUpperCase()} · ~${d.estimated_monthly_usd.toFixed(2)}/mo · {new Date(d.created_at).toLocaleString()}</small>
                {d.url && <a className="st-link" href={d.url} target="_blank" rel="noreferrer"><ExternalLink size={11} /> {d.url.replace(/^https?:\/\//, '')}</a>}
                {d.log.length > 0 && <small className="dp-log">{d.log[d.log.length - 1].message}</small>}
                {!readOnly && d.status === 'superseded' && (
                  <button type="button" className="st-link" disabled={rollback.isPending} onClick={() => rollback.mutate(d.id)}><RotateCcw size={11} /> Roll back to this version</button>
                )}
              </li>
            ))}
          </ol>
          {rollback.error && <p className="st-error">{rollback.error.message}</p>}
        </section>
      )}
    </div>
  )
}
