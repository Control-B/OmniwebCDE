import { Link, createFileRoute, notFound } from '@tanstack/react-router'
import {
  ArrowRight, Check, CircleDot, GitBranch, Layers3, LineChart, ShieldCheck, Sparkles,
} from 'lucide-react'

import { EXPLORE_BY_SLUG, EXPLORE_ITEMS } from '../lib/explore'
import { LandingNav } from './index'

export const Route = createFileRoute('/explore/$slug')({
  loader: ({ params }) => {
    const item = EXPLORE_BY_SLUG.get(params.slug)
    if (!item) throw notFound()
    return item
  },
  head: ({ loaderData }) => ({
    meta: [{
      title: loaderData ? `${loaderData.title} — Omniweb` : 'Explore Omniweb',
    }],
  }),
  component: ExplorePage,
})

function ExplorePage() {
  const item = Route.useLoaderData()
  const related = EXPLORE_ITEMS
    .filter((candidate) => candidate.category === item.category && candidate.slug !== item.slug)
    .slice(0, 3)

  return (
    <div className="lv ex">
      <LandingNav />
      <main>
        <section className="ex-hero">
          <div className="lv-wrap ex-hero-grid">
            <div className="ex-copy">
              <span className="ex-eyebrow"><Sparkles size={14} /> {item.category}</span>
              <h1>{item.title}</h1>
              <p className="ex-lede">{item.summary}</p>
              <p className="ex-audience">{item.audience}</p>
              <div className="ex-actions">
                <Link to="/create" className="lv-btn lv-btn-light lv-btn-lg">Start with Unified Create <ArrowRight size={16} /></Link>
                <Link to="/projects" className="lv-btn ex-secondary">View projects</Link>
              </div>
            </div>
            <div className="ex-visual" aria-label={`${item.title} connected workflow`}>
              <div className="ex-visual-glow" />
              <div className="ex-flow-card primary">
                <span><Sparkles size={16} /></span>
                <div><small>Business intent</small><strong>{item.title}</strong></div>
              </div>
              <div className="ex-flow-line one" />
              <div className="ex-flow-line two" />
              <div className="ex-flow-card left"><span><Layers3 size={15} /></span><div><small>Execution</small><strong>Connected tasks</strong></div></div>
              <div className="ex-flow-card right"><span><ShieldCheck size={15} /></span><div><small>Governance</small><strong>Approval gates</strong></div></div>
              <div className="ex-flow-card bottom"><span><LineChart size={15} /></span><div><small>Feedback</small><strong>Measured outcomes</strong></div></div>
            </div>
          </div>
        </section>

        <section className="ex-outcomes">
          <div className="lv-wrap">
            {item.outcomes.map((outcome) => <div key={outcome}><Check size={15} /><span>{outcome}</span></div>)}
          </div>
        </section>

        <section className="ex-section">
          <div className="lv-wrap">
            <div className="ex-section-head">
              <span>One connected workflow</span>
              <h2>From brief to verified outcome.</h2>
              <p>Omniweb keeps strategy, implementation, creative work, evidence, and approvals attached to the same project.</p>
            </div>
            <div className="ex-value-grid">
              <article>
                <span className="ex-card-num">01</span><CircleDot size={21} />
                <h3>Start with intent</h3>
                <p>Describe the result in natural language. AUTO mode identifies every related product, business, marketing, content, and media task.</p>
              </article>
              <article>
                <span className="ex-card-num">02</span><GitBranch size={21} />
                <h3>Execute with context</h3>
                <p>A dependency-aware graph coordinates specialist agents through the shared cost-aware execution engine.</p>
              </article>
              <article>
                <span className="ex-card-num">03</span><ShieldCheck size={21} />
                <h3>Verify before action</h3>
                <p>Tests, evidence, tenant boundaries, budgets, and explicit approval gates protect every consequential action.</p>
              </article>
            </div>
          </div>
        </section>

        <section className="ex-section ex-dark">
          <div className="lv-wrap ex-prompt-grid">
            <div>
              <span className="ex-eyebrow"><Sparkles size={14} /> Try it in Omniweb</span>
              <h2>One sentence is enough to start.</h2>
              <p>Use this as a starting point, then refine the plan, assets, implementation, and approvals in the same conversation.</p>
            </div>
            <div className="ex-prompt-card">
              <span>Example prompt</span>
              <p>“{item.prompt}”</p>
              <Link to="/create">Open Unified Create <ArrowRight size={15} /></Link>
            </div>
          </div>
        </section>

        <section className="ex-section">
          <div className="lv-wrap">
            <div className="ex-section-head compact"><span>Keep exploring</span><h2>More for {item.category.toLowerCase()}.</h2></div>
            <div className="ex-related">
              {related.map((candidate) => (
                <Link key={candidate.slug} to="/explore/$slug" params={{ slug: candidate.slug }}>
                  <small>{candidate.category}</small><strong>{candidate.title}</strong><p>{candidate.summary}</p><span>Explore <ArrowRight size={14} /></span>
                </Link>
              ))}
            </div>
          </div>
        </section>

        <section className="ex-final">
          <div className="lv-wrap">
            <div><span>Ready to begin?</span><h2>Create the connected system, not another isolated asset.</h2></div>
            <Link to="/create" className="lv-btn lv-btn-light lv-btn-lg">Get started <ArrowRight size={16} /></Link>
          </div>
        </section>
      </main>
      <footer className="lv-footer"><div className="lv-wrap lv-footer-inner"><Link to="/" className="lv-brand"><span className="lv-mark" />Omniweb</Link><span className="lv-muted">© {new Date().getFullYear()} Omniweb</span></div></footer>
    </div>
  )
}
