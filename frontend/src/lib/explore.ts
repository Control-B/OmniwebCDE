export type ExploreCategory = 'Platform' | 'Solutions' | 'Developers' | 'Resources'

export interface ExploreItem {
  slug: string
  title: string
  navText: string
  category: ExploreCategory
  summary: string
  audience: string
  outcomes: [string, string, string]
  prompt: string
}

export const PLATFORM_ITEMS: ExploreItem[] = [
  {
    slug: 'unified-create', title: 'Unified Create', navText: 'Plan, build, and grow from one prompt.',
    category: 'Platform', summary: 'Turn one business brief into connected product, strategy, campaign, and creative work.',
    audience: 'Teams that want one contextual workspace instead of disconnected AI tools.',
    outcomes: ['Multi-intent planning', 'Dependency-aware execution', 'Approval-gated delivery'],
    prompt: 'Plan my business, build its customer portal, and create the launch campaign.',
  },
  {
    slug: 'application-builder', title: 'Application Builder', navText: 'Generate and refine production-ready apps.',
    category: 'Platform', summary: 'Create full-stack web and mobile applications with real code, previews, tests, and checkpoints.',
    audience: 'Founders and product teams moving from requirements to verified software.',
    outcomes: ['Editable source code', 'Sandboxed verification', 'Preview and release approvals'],
    prompt: 'Build a customer booking application with onboarding, scheduling, and analytics.',
  },
  {
    slug: 'business-planner', title: 'Business Planner', navText: 'Turn evidence and assumptions into a roadmap.',
    category: 'Platform', summary: 'Develop an editable business plan that clearly separates sourced facts, assumptions, and projections.',
    audience: 'Operators validating an opportunity before committing product and marketing spend.',
    outcomes: ['Market and segment analysis', 'Scenario-based financial assumptions', 'Actionable implementation roadmap'],
    prompt: 'Create an evidence-aware plan for a local services marketplace.',
  },
  {
    slug: 'marketing-studio', title: 'Marketing Studio', navText: 'Create campaigns, funnels, and experiments.',
    category: 'Platform', summary: 'Plan and operate measurable campaigns with audience research, calendars, funnels, and approval controls.',
    audience: 'Marketing teams that need strategy and execution to share the same evidence.',
    outcomes: ['Campaign orchestration', 'Funnel analytics', 'Controlled A/B experiments'],
    prompt: 'Launch a lead-generation campaign with a funnel, content calendar, and measurable objectives.',
  },
  {
    slug: 'content-studio', title: 'Content Studio', navText: 'Create governed text, image, and video assets.',
    category: 'Platform', summary: 'Generate, edit, version, approve, and reuse campaign and product content from a shared asset library.',
    audience: 'Creative teams producing consistent content across websites, email, social, and advertising.',
    outcomes: ['Versioned asset library', 'Brand-kit reuse', 'Rights and cost metadata'],
    prompt: 'Create a month of on-brand articles, emails, social posts, and visual briefs.',
  },
  {
    slug: 'cloud-workspaces', title: 'Cloud Workspaces', navText: 'Build securely in isolated environments.',
    category: 'Platform', summary: 'Give every software task an isolated development environment with governed access and lifecycle controls.',
    audience: 'Engineering teams that need secure, repeatable workspaces without local setup drift.',
    outcomes: ['Isolated environments', 'Cost approval controls', 'Browser IDE and console access'],
    prompt: 'Create a secure full-stack workspace for my product team.',
  },
  {
    slug: 'ai-usage-budgets', title: 'AI Usage & Budgets', navText: 'Control models, routing, and spend.',
    category: 'Platform', summary: 'Route work by capability, risk, and cost while keeping every model request attributable.',
    audience: 'Administrators governing AI quality, providers, and spending across an organization.',
    outcomes: ['Cost-aware routing', 'Provider and model controls', 'Tenant and project budgets'],
    prompt: 'Show me how to set separate text, software, image, and video budgets.',
  },
  {
    slug: 'capability-evolution', title: 'Capability Evolution', navText: 'Connect product releases and market evidence.',
    category: 'Platform', summary: 'Use verified marketing evidence to propose software improvements—and released capabilities to propose marketing updates.',
    audience: 'Teams closing the loop between customer behavior, product delivery, and go-to-market work.',
    outcomes: ['Evidence-linked hypotheses', 'Catalog reuse or synthesis', 'Measured post-release outcomes'],
    prompt: 'Turn funnel abandonment evidence into a traceable software improvement proposal.',
  },
]

export const SOLUTION_ITEMS: ExploreItem[] = [
  ['for-work', 'For Work', 'Run on what you build.', 'Connect internal operations, customer experiences, and measurable growth in one workspace.'],
  ['founders', 'Founders', 'Ship before you pitch.', 'Move from business thesis to tested product and launch campaign without losing context.'],
  ['marketers', 'Marketers', 'Launch complete campaigns faster.', 'Create strategy, funnels, content, experiments, and analytics from a single campaign brief.'],
  ['sales', 'Sales', 'Build the demo live.', 'Create customer-ready portals, lead journeys, and follow-up systems around real sales needs.'],
  ['product-managers', 'Product managers', 'Prototype, test, and learn.', 'Translate evidence into requirements, verified builds, experiments, and measured outcomes.'],
  ['designers', 'Designers', 'Turn intent into working experiences.', 'Generate responsive interfaces, refine them visually, and preserve every approved version.'],
  ['operations', 'Operations', 'Create tools that fit your flow.', 'Build internal tools and automations around the way your team actually works.'],
  ['agencies', 'Agencies', 'Operate every client workspace.', 'Manage client software, campaigns, assets, approvals, and AI budgets with tenant isolation.'],
  ['websites', 'Websites', 'From idea to live site.', 'Build responsive sites, landing pages, conversion journeys, and supporting content together.'],
  ['ai-powered-apps', 'AI-powered apps', 'Apps that reason, create, and act.', 'Develop governed AI experiences with bounded tools, model routing, and auditable execution.'],
  ['prototyping', 'Prototyping', 'Proof of concept with real code.', 'Explore a product direction through an editable, testable application instead of a disposable mockup.'],
  ['internal-tools', 'Internal tools', 'Built for your team.', 'Create secure operational applications, workflows, and integrations around your business processes.'],
].map(([slug, title, navText, summary]) => ({
  slug, title, navText, summary, category: 'Solutions' as const,
  audience: `${title} teams that need software and go-to-market execution to stay connected.`,
  outcomes: ['Faster path to a working result', 'Shared project and campaign context', 'Approval and budget controls'] as [string, string, string],
  prompt: `Create an Omniweb workspace for ${title.toLowerCase()} and propose the first complete workflow.`,
}))

export const DEVELOPER_ITEMS: ExploreItem[] = [
  ['developer-platform', 'Platform overview', 'Build on Omniweb’s connected platform.', 'Use project, asset, campaign, evidence, and execution primitives without rebuilding platform governance.'],
  ['api-reference', 'API reference', 'Integrate through typed service contracts.', 'Connect approved systems to Omniweb’s tenant-scoped application and intelligence APIs.'],
  ['sdk-tools', 'SDKs & tools', 'Automate common development workflows.', 'Build integrations and operator tooling on stable contracts and bounded execution patterns.'],
  ['mcp-integrations', 'MCP integrations', 'Connect authorized tools and data.', 'Expose provider capabilities through governed adapters with explicit authentication and egress boundaries.'],
  ['webhooks', 'Webhooks', 'React to verified lifecycle events.', 'Receive approved release, campaign, lead, workflow, and capability-evolution events safely.'],
  ['cloud-development', 'Cloud development', 'Code in isolated browser workspaces.', 'Provision governed development environments with controlled credentials and cost approval.'],
  ['sample-catalog', 'Sample code catalog', 'Start from tested capability patterns.', 'Reuse implementation patterns for authentication, scheduling, lead capture, analytics, and onboarding.'],
  ['developer-guides', 'Developer guides', 'Learn architecture and operating patterns.', 'Follow practical guides for integrations, agents, media adapters, security boundaries, and deployment.'],
].map(([slug, title, navText, summary]) => ({
  slug, title, navText, summary, category: 'Developers' as const,
  audience: 'Developers extending Omniweb or connecting it to an authorized business system.',
  outcomes: ['Tenant-scoped contracts', 'Auditable integrations', 'Reusable implementation patterns'] as [string, string, string],
  prompt: `Show me how to use ${title.toLowerCase()} for an Omniweb project.`,
}))

export const RESOURCE_ITEMS: ExploreItem[] = [
  ['templates', 'Templates', 'Begin with a tested foundation.', 'Explore starting points for websites, applications, funnels, campaigns, and operational workflows.'],
  ['guides', 'Guides', 'Learn by building complete outcomes.', 'Follow practical walkthroughs from business brief through software, campaign, and measurement.'],
  ['customer-stories', 'Customer stories', 'See connected work in practice.', 'Learn how teams align product delivery and growth work around shared evidence and approvals.'],
  ['trust-center', 'Trust & security', 'Understand platform safeguards.', 'Review tenant isolation, approvals, credential boundaries, auditability, and secure execution principles.'],
  ['resource-library', 'Resource library', 'Research for builders and operators.', 'Browse structured material for planning, product development, marketing, content, and experimentation.'],
  ['community', 'Community', 'Build and learn with other teams.', 'Exchange patterns and practical lessons for creating software and growing businesses with Omniweb.'],
  ['product-news', 'Product news', 'Follow verified platform releases.', 'See what changed, who it is available to, and how each release can support your workflow.'],
  ['help-center', 'Help center', 'Get answers for your workspace.', 'Find concise guidance for projects, campaigns, assets, permissions, budgets, and provider setup.'],
].map(([slug, title, navText, summary]) => ({
  slug, title, navText, summary, category: 'Resources' as const,
  audience: 'Teams evaluating, adopting, or operating Omniweb.',
  outcomes: ['Practical implementation guidance', 'Transparent platform boundaries', 'Reusable examples and patterns'] as [string, string, string],
  prompt: `Help me use ${title.toLowerCase()} to plan my next Omniweb project.`,
}))

export const EXPLORE_ITEMS = [
  ...PLATFORM_ITEMS,
  ...SOLUTION_ITEMS,
  ...DEVELOPER_ITEMS,
  ...RESOURCE_ITEMS,
]

export const EXPLORE_BY_SLUG = new Map(EXPLORE_ITEMS.map((item) => [item.slug, item]))
