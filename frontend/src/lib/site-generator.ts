export type SiteKind = 'saas' | 'portfolio' | 'restaurant' | 'agency' | 'store' | 'fitness' | 'event'
export type SectionId = 'features' | 'showcase' | 'stats' | 'testimonials' | 'pricing' | 'faq' | 'contact' | 'cta'
export type SiteStyle = 'modern' | 'elegant' | 'playful' | 'minimal' | 'bold'
export type PaletteName = 'violet' | 'blue' | 'green' | 'orange' | 'pink' | 'red' | 'teal' | 'mono' | 'gold'

export interface SiteSpec {
  name: string
  kind: SiteKind
  headline: string
  subheadline: string
  cta: string
  palette: PaletteName
  dark: boolean
  style: SiteStyle
  radius: number
  sections: SectionId[]
}

const PALETTES: Record<PaletteName, [string, string]> = {
  violet: ['#6d28d9', '#db2777'],
  blue: ['#2563eb', '#06b6d4'],
  green: ['#047857', '#65a30d'],
  orange: ['#ea580c', '#f59e0b'],
  pink: ['#db2777', '#f97316'],
  red: ['#dc2626', '#f97316'],
  teal: ['#0f766e', '#3b82f6'],
  mono: ['#18181b', '#71717a'],
  gold: ['#a16207', '#b45309'],
}

const FONTS: Record<SiteStyle, { heading: string; body: string; query: string }> = {
  modern: { heading: "'Inter Tight', sans-serif", body: "'Inter', sans-serif", query: 'Inter+Tight:wght@500;600;700;800&family=Inter:wght@400;500;600' },
  elegant: { heading: "'Fraunces', serif", body: "'Inter', sans-serif", query: 'Fraunces:opsz,wght@9..144,400;9..144,600&family=Inter:wght@400;500;600' },
  playful: { heading: "'Bricolage Grotesque', sans-serif", body: "'DM Sans', sans-serif", query: 'Bricolage+Grotesque:wght@500;700;800&family=DM+Sans:wght@400;500;700' },
  minimal: { heading: "'Inter', sans-serif", body: "'Inter', sans-serif", query: 'Inter:wght@300;400;500;600' },
  bold: { heading: "'Archivo Black', sans-serif", body: "'Archivo', sans-serif", query: 'Archivo+Black&family=Archivo:wght@400;500;700' },
}

interface KindContent {
  label: string
  nav: string[]
  eyebrow: string
  headline: (name: string) => string
  sub: string
  cta: string
  secondary: string
  features: [string, string][]
  showcaseTitle: string
  showcase: { title: string; meta: string; tag: string }[]
  stats: [string, string][]
  testimonials: [string, string, string][]
  pricing: { name: string; price: string; period: string; features: string[]; featured?: boolean }[]
  faq: [string, string][]
  palette: PaletteName
  style: SiteStyle
  sections: SectionId[]
  defaultName: string
}

const CONTENT: Record<SiteKind, KindContent> = {
  saas: {
    label: 'SaaS product',
    nav: ['Product', 'Customers', 'Pricing', 'Docs'],
    eyebrow: 'Now with AI workflows',
    headline: () => 'Ship your best work, faster than ever',
    sub: 'One focused workspace for planning, building, and launching. Fewer tabs, clearer priorities, and a team that always knows what is next.',
    cta: 'Start free trial',
    secondary: 'Book a demo',
    features: [
      ['Plan in minutes', 'Turn rough ideas into structured roadmaps with smart templates and automatic prioritization.'],
      ['Real-time collaboration', 'Comments, presence, and live editing keep every teammate on the same page.'],
      ['Insights that matter', 'Dashboards surface blockers and velocity trends before they become problems.'],
    ],
    showcaseTitle: 'Built for every team',
    showcase: [
      { title: 'Product teams', meta: 'Roadmaps, specs, and launches', tag: 'Plan' },
      { title: 'Engineering', meta: 'Sprints, reviews, and releases', tag: 'Build' },
      { title: 'Marketing', meta: 'Campaigns and content calendars', tag: 'Launch' },
    ],
    stats: [['12k+', 'Teams onboard'], ['38%', 'Faster delivery'], ['99.99%', 'Uptime'], ['4.9/5', 'Average rating']],
    testimonials: [
      ['We replaced four tools in a week. Our planning meetings went from an hour to fifteen minutes.', 'Maya Chen', 'VP Product, Northwind'],
      ['The first product our engineers actually enjoy updating. Visibility has never been better.', 'Daniel Ortiz', 'CTO, Brightline'],
      ['Onboarding took an afternoon. Results showed up in the very first sprint.', 'Priya Nair', 'Head of Ops, Lumen'],
    ],
    pricing: [
      { name: 'Starter', price: '$0', period: '/month', features: ['Up to 5 members', 'Unlimited projects', 'Core integrations'] },
      { name: 'Pro', price: '$18', period: '/user/mo', features: ['Unlimited members', 'Advanced insights', 'Automations', 'Priority support'], featured: true },
      { name: 'Enterprise', price: 'Custom', period: '', features: ['SSO & SCIM', 'Audit logs', 'Dedicated success manager'] },
    ],
    faq: [
      ['Is there a free plan?', 'Yes. Starter is free forever for small teams with unlimited projects.'],
      ['Can I import from other tools?', 'One-click importers bring over your projects, tasks, and history.'],
      ['Is my data secure?', 'Data is encrypted in transit and at rest, with SOC 2 Type II controls.'],
    ],
    palette: 'violet',
    style: 'modern',
    sections: ['features', 'showcase', 'stats', 'testimonials', 'pricing', 'faq', 'cta'],
    defaultName: 'Flowstate',
  },
  portfolio: {
    label: 'Portfolio',
    nav: ['Work', 'About', 'Services', 'Contact'],
    eyebrow: 'Available for new projects',
    headline: () => 'Crafting images that tell quiet, honest stories',
    sub: 'Independent photographer and visual storyteller working with brands, editors, and people who care about the details.',
    cta: 'View selected work',
    secondary: 'Get in touch',
    features: [
      ['Editorial', 'Narrative series for magazines and publications around the world.'],
      ['Brand campaigns', 'Considered imagery that gives products a sense of place and purpose.'],
      ['Portraits', 'Natural, unhurried sessions that feel like you on your best day.'],
    ],
    showcaseTitle: 'Selected work',
    showcase: [
      { title: 'Salt & Stone', meta: 'Editorial · Iceland, 2026', tag: 'Editorial' },
      { title: 'Quiet Hours', meta: 'Campaign · Aesop', tag: 'Brand' },
      { title: 'Faces of Lisbon', meta: 'Personal series, 2025', tag: 'Portrait' },
    ],
    stats: [['11', 'Years shooting'], ['40+', 'Brand partners'], ['16', 'Countries'], ['3', 'Book releases']],
    testimonials: [
      ['Every frame felt intentional. The campaign outperformed anything we had shot before.', 'Elena Rossi', 'Creative Director, Mara'],
      ['Calm on set, relentless about craft. Exactly who you want behind the camera.', 'James Holt', 'Photo Editor, Field Journal'],
      ['Our portraits finally feel like us. We could not stop looking at them.', 'Sana & Theo', 'Private clients'],
    ],
    pricing: [
      { name: 'Portrait', price: '$650', period: '/session', features: ['2-hour session', '25 edited images', 'Online gallery'] },
      { name: 'Brand day', price: '$3,200', period: '/day', features: ['Full-day production', 'Art direction', 'Usage license'], featured: true },
      { name: 'Editorial', price: 'Quote', period: '', features: ['Travel worldwide', 'Story development', 'Licensing options'] },
    ],
    faq: [
      ['Do you travel?', 'Yes, I work worldwide. Travel is quoted per project.'],
      ['How soon will I receive images?', 'Portrait galleries arrive within two weeks; campaigns follow the agreed schedule.'],
      ['Can we license existing work?', 'Many images from my archive are available for licensing. Just ask.'],
    ],
    palette: 'mono',
    style: 'elegant',
    sections: ['showcase', 'features', 'testimonials', 'contact'],
    defaultName: 'Ava Lindqvist',
  },
  restaurant: {
    label: 'Restaurant',
    nav: ['Menu', 'Story', 'Private dining', 'Visit'],
    eyebrow: 'Open Tuesday – Sunday',
    headline: () => 'Seasonal cooking, wood fire, and good company',
    sub: 'A neighborhood kitchen built around local farms, open flame, and a wine list that rewards curiosity.',
    cta: 'Reserve a table',
    secondary: 'See the menu',
    features: [
      ['Farm to fire', 'Produce from farms within 60 miles, cooked over seasoned oak.'],
      ['Natural wine', 'Over 200 bottles from small growers, with daily pours by the glass.'],
      ['Private dining', 'A twelve-seat chef’s table for celebrations and long dinners.'],
    ],
    showcaseTitle: 'From the menu',
    showcase: [
      { title: 'Charred leeks', meta: 'Romesco, hazelnut, sea salt', tag: '$16' },
      { title: 'Wood-fired bream', meta: 'Brown butter, capers, lemon', tag: '$34' },
      { title: 'Burnt honey tart', meta: 'Crème fraîche, thyme', tag: '$12' },
    ],
    stats: [['60 mi', 'Sourcing radius'], ['200+', 'Wines'], ['12', 'Chef’s table seats'], ['2026', 'Michelin Bib']],
    testimonials: [
      ['The best meal we have had all year. The bream alone is worth the trip.', 'The Evening Post', 'Restaurant review'],
      ['Warm, unpretentious, and exceptional. We are already planning our next visit.', 'Laura M.', 'Guest'],
      ['A wine list that makes you want to try everything. Staff guided us perfectly.', 'Ben K.', 'Guest'],
    ],
    pricing: [
      { name: 'Lunch', price: '$38', period: '/person', features: ['Three courses', 'Tue – Fri', 'Seasonal set'] },
      { name: 'Tasting menu', price: '$95', period: '/person', features: ['Seven courses', 'Wine pairing available', 'Nightly'], featured: true },
      { name: 'Chef’s table', price: '$150', period: '/person', features: ['Up to 12 guests', 'Custom menu', 'Pairings included'] },
    ],
    faq: [
      ['Do you accommodate dietary needs?', 'Absolutely. Let us know when booking and the kitchen will adapt.'],
      ['Do you take walk-ins?', 'Yes, our bar seats are held for walk-ins every evening.'],
      ['Is there parking?', 'Street parking is available, with a public garage one block away.'],
    ],
    palette: 'orange',
    style: 'elegant',
    sections: ['showcase', 'features', 'testimonials', 'pricing', 'contact'],
    defaultName: 'Ember & Oak',
  },
  agency: {
    label: 'Agency',
    nav: ['Work', 'Services', 'Studio', 'Contact'],
    eyebrow: 'Independent design studio',
    headline: () => 'We build brands people remember',
    sub: 'Strategy, identity, and digital products for ambitious companies that refuse to blend in.',
    cta: 'Start a project',
    secondary: 'See our work',
    features: [
      ['Brand strategy', 'Positioning, naming, and narrative that give your company a point of view.'],
      ['Identity systems', 'Logos, type, color, and motion designed to scale across every touchpoint.'],
      ['Digital products', 'Websites and apps that look beautiful and convert relentlessly.'],
    ],
    showcaseTitle: 'Recent work',
    showcase: [
      { title: 'Halcyon Bank', meta: 'Rebrand & digital banking app', tag: 'Fintech' },
      { title: 'Verdant', meta: 'Identity for a climate venture fund', tag: 'Brand' },
      { title: 'Atlas Travel', meta: 'Booking platform redesign', tag: 'Product' },
    ],
    stats: [['120+', 'Brands launched'], ['24', 'Design awards'], ['3.2x', 'Average conversion lift'], ['9', 'Countries']],
    testimonials: [
      ['They challenged every assumption and gave us a brand we are genuinely proud of.', 'Nora Patel', 'CEO, Halcyon'],
      ['The launch doubled our inbound pipeline in a month.', 'Marcus Lee', 'CMO, Atlas'],
      ['Rare combination of strategic depth and beautiful craft.', 'Ines Duarte', 'Founder, Verdant'],
    ],
    pricing: [
      { name: 'Sprint', price: '$18k', period: '', features: ['Two-week engagement', 'Brand audit', 'Direction workshop'] },
      { name: 'Brand system', price: '$65k', period: '', features: ['Strategy & naming', 'Full identity', 'Guidelines & assets'], featured: true },
      { name: 'Partnership', price: 'Retainer', period: '', features: ['Embedded team', 'Ongoing design', 'Quarterly strategy'] },
    ],
    faq: [
      ['How long does a rebrand take?', 'Most brand systems take 10–14 weeks from kickoff to launch.'],
      ['Do you work with startups?', 'Yes. Our sprint format is designed for early-stage teams.'],
      ['Where are you based?', 'We are a remote-first studio with partners in New York and Lisbon.'],
    ],
    palette: 'blue',
    style: 'bold',
    sections: ['showcase', 'features', 'stats', 'testimonials', 'cta'],
    defaultName: 'Northbound',
  },
  store: {
    label: 'Online store',
    nav: ['Shop', 'Collections', 'Journal', 'Cart'],
    eyebrow: 'Free shipping over $75',
    headline: () => 'Everyday objects, made to last a lifetime',
    sub: 'Thoughtfully designed essentials for home and table, crafted in small batches by independent makers.',
    cta: 'Shop the collection',
    secondary: 'Our makers',
    features: [
      ['Made to last', 'Durable materials and honest construction, backed by a lifetime guarantee.'],
      ['Small-batch makers', 'Every piece comes from an independent studio we know by name.'],
      ['Carbon-neutral shipping', 'Plastic-free packaging, with every order offset at checkout.'],
    ],
    showcaseTitle: 'Bestsellers',
    showcase: [
      { title: 'Stoneware mug', meta: 'Hand-glazed · Sand', tag: '$32' },
      { title: 'Linen throw', meta: 'Stonewashed · Oat', tag: '$128' },
      { title: 'Oak serving board', meta: 'Oiled finish · Large', tag: '$74' },
    ],
    stats: [['48k', 'Happy homes'], ['4.9★', 'Average review'], ['32', 'Makers'], ['100%', 'Plastic-free']],
    testimonials: [
      ['The linen throw is the softest thing I own. It lives on our sofa now.', 'Hannah W.', 'Verified buyer'],
      ['Gorgeous packaging and the mugs are even better in person.', 'Omar S.', 'Verified buyer'],
      ['Finally a store where everything is genuinely good.', 'Clara D.', 'Verified buyer'],
    ],
    pricing: [
      { name: 'Essentials', price: '$89', period: '', features: ['Two mugs', 'Linen napkins', 'Gift wrap'] },
      { name: 'The Table Set', price: '$249', period: '', features: ['Serving board', 'Four mugs', 'Linen runner'], featured: true },
      { name: 'Gift card', price: 'From $25', period: '', features: ['Delivered by email', 'Never expires'] },
    ],
    faq: [
      ['What is your return policy?', 'Free returns within 60 days, no questions asked.'],
      ['Do you ship internationally?', 'We ship to 40+ countries with duties included at checkout.'],
      ['How do I care for linen?', 'Machine wash cold and line dry. It gets softer with every wash.'],
    ],
    palette: 'gold',
    style: 'minimal',
    sections: ['showcase', 'features', 'testimonials', 'faq', 'cta'],
    defaultName: 'Hearth Goods',
  },
  fitness: {
    label: 'Fitness studio',
    nav: ['Classes', 'Coaches', 'Membership', 'Visit'],
    eyebrow: 'First class free',
    headline: () => 'Train hard. Recover well. Feel unstoppable.',
    sub: 'Strength, conditioning, and mobility classes led by coaches who know your name and push your limits.',
    cta: 'Book your free class',
    secondary: 'View schedule',
    features: [
      ['Small classes', 'Never more than 14 people, so every rep gets real coaching.'],
      ['Programmed progress', 'Twelve-week cycles designed to build measurable strength.'],
      ['Recovery lounge', 'Sauna, cold plunge, and mobility space included with membership.'],
    ],
    showcaseTitle: 'Signature classes',
    showcase: [
      { title: 'Strength Lab', meta: '60 min · All levels', tag: 'Strength' },
      { title: 'Engine', meta: '45 min · Conditioning', tag: 'Cardio' },
      { title: 'Flow & Restore', meta: '50 min · Mobility', tag: 'Recovery' },
    ],
    stats: [['14', 'Max class size'], ['60+', 'Weekly classes'], ['9', 'Expert coaches'], ['4.9', 'Google rating']],
    testimonials: [
      ['I deadlifted my bodyweight for the first time at 42. The coaching is next level.', 'Rachel T.', 'Member since 2024'],
      ['The community is the reason I never skip a session.', 'Kofi A.', 'Member since 2023'],
      ['Cold plunge after Engine class is my new favorite ritual.', 'Lena P.', 'Member since 2025'],
    ],
    pricing: [
      { name: 'Drop-in', price: '$28', period: '/class', features: ['Any class', 'Towel service', 'No commitment'] },
      { name: 'Unlimited', price: '$189', period: '/month', features: ['Unlimited classes', 'Recovery lounge', 'Progress tracking'], featured: true },
      { name: '10-pack', price: '$240', period: '', features: ['Ten classes', 'Valid 6 months', 'Shareable'] },
    ],
    faq: [
      ['I am a beginner. Is that okay?', 'Absolutely. Every class has scaling options and coaches guide you through form.'],
      ['What should I bring?', 'Just water and trainers. We provide towels and equipment.'],
      ['Can I freeze my membership?', 'Yes, up to two months per year at no cost.'],
    ],
    palette: 'red',
    style: 'bold',
    sections: ['showcase', 'features', 'stats', 'pricing', 'testimonials', 'faq', 'cta'],
    defaultName: 'Forge Athletics',
  },
  event: {
    label: 'Event',
    nav: ['Speakers', 'Agenda', 'Venue', 'Tickets'],
    eyebrow: 'June 18–19 · San Francisco',
    headline: () => 'Two days with the people building what’s next',
    sub: 'Talks, workshops, and unforgettable conversations with 2,000 founders, designers, and engineers.',
    cta: 'Get your ticket',
    secondary: 'See the agenda',
    features: [
      ['40+ speakers', 'Founders and builders from the most exciting companies of the year.'],
      ['Hands-on workshops', 'Small-group sessions where you leave with something you built.'],
      ['Curated networking', 'Smart matching introduces you to the people worth meeting.'],
    ],
    showcaseTitle: 'Featured speakers',
    showcase: [
      { title: 'Amara Okafor', meta: 'Founder & CEO, Lattice AI', tag: 'Keynote' },
      { title: 'Jonas Berg', meta: 'Head of Design, Polar', tag: 'Design' },
      { title: 'Sofia Ramirez', meta: 'Partner, Horizon Ventures', tag: 'Fireside' },
    ],
    stats: [['2,000', 'Attendees'], ['40+', 'Speakers'], ['24', 'Workshops'], ['2', 'Days']],
    testimonials: [
      ['The most valuable two days of my year. I met our lead investor here.', 'Tom Becker', 'Founder, Relay'],
      ['Workshops were genuinely hands-on. I shipped a prototype on day one.', 'Aisha Khan', 'Product Designer'],
      ['Incredible energy and impeccably organized.', 'Leo Martins', 'Engineering Lead'],
    ],
    pricing: [
      { name: 'Standard', price: '$499', period: '', features: ['Both days', 'All talks', 'Lunch & coffee'] },
      { name: 'All-access', price: '$899', period: '', features: ['Everything in Standard', 'Workshops', 'Speaker dinner'], featured: true },
      { name: 'Student', price: '$149', period: '', features: ['Both days', 'All talks', 'Valid student ID'] },
    ],
    faq: [
      ['Is the event recorded?', 'Main stage talks are recorded and shared with ticket holders.'],
      ['Can I transfer my ticket?', 'Yes, tickets can be transferred until one week before the event.'],
      ['Are there group discounts?', 'Teams of five or more save 15% automatically.'],
    ],
    palette: 'pink',
    style: 'playful',
    sections: ['showcase', 'features', 'stats', 'pricing', 'faq', 'cta'],
    defaultName: 'Frontier Summit',
  },
}

const KIND_KEYWORDS: [SiteKind, RegExp][] = [
  ['restaurant', /restaurant|cafe|café|coffee|bakery|bistro|bar\b|menu|food|pizza|sushi|kitchen|dining/i],
  ['portfolio', /portfolio|photographer|photography|designer|artist|illustrat|personal site|resume|cv\b|freelanc/i],
  ['store', /store|shop|e-?commerce|products?|boutique|brand of|merch|sell/i],
  ['fitness', /gym|fitness|yoga|pilates|crossfit|studio class|trainer|workout|wellness/i],
  ['event', /event|conference|summit|festival|meetup|wedding|concert|hackathon/i],
  ['agency', /agency|studio|consult|marketing firm|law firm|architect|creative/i],
  ['saas', /saas|startup|app|software|platform|tool|dashboard|ai\b|product/i],
]

const COLOR_KEYWORDS: [PaletteName, RegExp][] = [
  ['violet', /violet|purple|lavender|indigo/i],
  ['blue', /\bblue|navy|ocean|sky/i],
  ['green', /green|emerald|forest|sage|eco/i],
  ['orange', /orange|amber|sunset|warm/i],
  ['pink', /pink|rose|magenta|fuchsia/i],
  ['red', /\bred\b|crimson|scarlet/i],
  ['teal', /teal|cyan|aqua|turquoise|mint/i],
  ['mono', /black and white|monochrome|grayscale|greyscale|\bmono\b/i],
  ['gold', /gold|brown|earthy|beige|cream|luxury/i],
]

const STYLE_KEYWORDS: [SiteStyle, RegExp][] = [
  ['elegant', /elegant|luxur|serif|classy|sophisticated|editorial/i],
  ['playful', /playful|fun|friendly|colorful|colourful|quirky/i],
  ['minimal', /minimal|clean|simple|calm|scandinavian/i],
  ['bold', /bold|brutal|loud|strong|striking/i],
  ['modern', /modern|sleek|futuristic|techy/i],
]

const SECTION_KEYWORDS: [SectionId, RegExp][] = [
  ['pricing', /pricing|prices|plans|tiers|packages/i],
  ['testimonials', /testimonial|reviews?|quotes/i],
  ['faq', /faq|questions/i],
  ['stats', /stats|numbers|metrics/i],
  ['contact', /contact|form|booking|newsletter|email signup/i],
  ['features', /features|benefits|services/i],
  ['showcase', /gallery|showcase|projects|products|menu|portfolio/i],
  ['cta', /call to action|cta|banner/i],
]

const SECTION_ORDER: SectionId[] = ['showcase', 'features', 'stats', 'testimonials', 'pricing', 'faq', 'contact', 'cta']

export const SECTION_LABELS: Record<SectionId, string> = {
  features: 'Features',
  showcase: 'Showcase',
  stats: 'Stats',
  testimonials: 'Testimonials',
  pricing: 'Pricing',
  faq: 'FAQ',
  contact: 'Contact',
  cta: 'Call to action',
}

function pick<T>(entries: [T, RegExp][], text: string): T | undefined {
  return entries.find(([, pattern]) => pattern.test(text))?.[0]
}

function titleCase(value: string): string {
  return value
    .trim()
    .replace(/\s+/g, ' ')
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function extractName(prompt: string): string | undefined {
  const quoted = prompt.match(/["“']([^"”']{2,40})["”']/)
  if (quoted) return quoted[1].trim()
  const named = prompt.match(/\b(?:called|named|for)\s+([A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,3})/)
  if (named) return named[1].trim()
  return undefined
}

function sortSections(sections: SectionId[]): SectionId[] {
  return SECTION_ORDER.filter((section) => sections.includes(section))
}

export function detectKind(prompt: string): SiteKind {
  return pick(KIND_KEYWORDS, prompt) ?? 'saas'
}

export function kindLabel(kind: SiteKind): string {
  return CONTENT[kind].label
}

export function createSpec(prompt: string): SiteSpec {
  const kind = detectKind(prompt)
  const content = CONTENT[kind]
  const name = extractName(prompt) ?? content.defaultName
  const requested = SECTION_KEYWORDS.filter(([, pattern]) => pattern.test(prompt)).map(([id]) => id)
  return {
    name,
    kind,
    headline: content.headline(name),
    subheadline: content.sub,
    cta: content.cta,
    palette: pick(COLOR_KEYWORDS, prompt) ?? content.palette,
    dark: /\bdark\b|night|black background/i.test(prompt),
    style: pick(STYLE_KEYWORDS, prompt) ?? content.style,
    radius: /sharp|square/i.test(prompt) ? 4 : /round|soft|pill/i.test(prompt) ? 24 : 14,
    sections: sortSections([...new Set([...content.sections, ...requested])]),
  }
}

export interface EditResult {
  spec: SiteSpec
  changes: string[]
}

export function applyEdit(spec: SiteSpec, instruction: string): EditResult {
  const next: SiteSpec = { ...spec, sections: [...spec.sections] }
  const changes: string[] = []
  const text = instruction.trim()

  const rename = text.match(/(?:rename(?: it)?(?: to)?|call it|name it|brand name(?: to)?)\s+["“']?([^"”'.!]{2,40})/i)
  if (rename) {
    next.name = titleCase(rename[1])
    changes.push(`Renamed the site to “${next.name}”`)
  }

  const headline = text.match(/(?:headline|title|heading)\s+(?:to|as|:)?\s*["“']([^"”']{3,120})["”']/i)
  if (headline) {
    next.headline = headline[1]
    changes.push('Rewrote the hero headline')
  }

  const subheadline = text.match(/(?:subheadline|subtitle|tagline|description)\s+(?:to|as|:)?\s*["“']([^"”']{3,240})["”']/i)
  if (subheadline) {
    next.subheadline = subheadline[1]
    changes.push('Updated the supporting copy')
  }

  const button = text.match(/(?:button|cta)\s+(?:text\s+)?(?:to|as|:|say)\s*["“']([^"”']{2,40})["”']/i)
  if (button) {
    next.cta = button[1]
    changes.push(`Changed the primary button to “${next.cta}”`)
  }

  const isRemoval = /\b(remove|delete|drop|hide|without|get rid of)\b/i.test(text)
  for (const [section, pattern] of SECTION_KEYWORDS) {
    if (!pattern.test(text) || headline || subheadline) continue
    if (isRemoval && next.sections.includes(section)) {
      next.sections = next.sections.filter((item) => item !== section)
      changes.push(`Removed the ${SECTION_LABELS[section].toLowerCase()} section`)
    } else if (!isRemoval && !next.sections.includes(section)) {
      next.sections = sortSections([...next.sections, section])
      changes.push(`Added a ${SECTION_LABELS[section].toLowerCase()} section`)
    }
  }

  const color = pick(COLOR_KEYWORDS, text)
  if (color && color !== next.palette) {
    next.palette = color
    changes.push(`Switched the palette to ${color}`)
  }

  if (/\bdark\b|night mode/i.test(text) && !next.dark) {
    next.dark = true
    changes.push('Moved to a dark theme')
  } else if (/\blight\b|bright|white background/i.test(text) && next.dark) {
    next.dark = false
    changes.push('Moved to a light theme')
  }

  const style = pick(STYLE_KEYWORDS, text)
  if (style && style !== next.style) {
    next.style = style
    changes.push(`Restyled the typography to feel ${style}`)
  }

  if (/sharp|square/i.test(text) && next.radius !== 4) {
    next.radius = 4
    changes.push('Sharpened corners across components')
  } else if (/round|soft|pill/i.test(text) && next.radius !== 24) {
    next.radius = 24
    changes.push('Softened corners across components')
  }

  const kind = /\b(make it|turn it into|switch to|change it to)\b/i.test(text) ? pick(KIND_KEYWORDS, text) : undefined
  if (kind && kind !== next.kind) {
    const content = CONTENT[kind]
    next.kind = kind
    next.headline = content.headline(next.name)
    next.subheadline = content.sub
    next.cta = content.cta
    next.sections = content.sections
    changes.push(`Rebuilt the site as a ${content.label.toLowerCase()}`)
  }

  return { spec: next, changes }
}

function esc(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
}

function heroVisual(spec: SiteSpec): string {
  const content = CONTENT[spec.kind]
  if (spec.kind === 'saas') {
    return `<div class="mock"><div class="mock-bar"><i></i><i></i><i></i><span>${esc(spec.name.toLowerCase().replace(/\s+/g, ''))}.app</span></div><div class="mock-body"><aside><b></b><b></b><b></b><b></b></aside><div><div class="mock-cards"><div><small>Velocity</small><strong>+38%</strong></div><div><small>Shipped</small><strong>142</strong></div><div><small>Blocked</small><strong>3</strong></div></div><div class="mock-chart">${[42, 64, 50, 78, 66, 88, 72, 96].map((h) => `<span style="height:${h}%"></span>`).join('')}</div></div></div></div>`
  }
  return `<div class="art"><div class="art-main"><span>${esc(content.showcase[0].tag)}</span><strong>${esc(content.showcase[0].title)}</strong></div><div class="art-float one"><small>${esc(content.stats[0][1])}</small><strong>${esc(content.stats[0][0])}</strong></div><div class="art-float two"><small>${esc(content.stats[3][1])}</small><strong>${esc(content.stats[3][0])}</strong></div></div>`
}

function renderSection(spec: SiteSpec, section: SectionId): string {
  const content = CONTENT[spec.kind]
  switch (section) {
    case 'features':
      return `<section class="section" id="features"><div class="wrap"><p class="kicker">Why ${esc(spec.name)}</p><h2>Everything you need, nothing you don’t</h2><div class="grid three">${content.features.map(([title, body], index) => `<article class="card feature"><div class="icon">${['✦', '◐', '▲'][index]}</div><h3>${esc(title)}</h3><p>${esc(body)}</p></article>`).join('')}</div></div></section>`
    case 'showcase': {
      const list = spec.kind === 'restaurant'
      return `<section class="section alt" id="showcase"><div class="wrap"><p class="kicker">${esc(content.nav[0])}</p><h2>${esc(content.showcaseTitle)}</h2>${list ? `<div class="menu">${content.showcase.map((item) => `<div class="menu-item"><div><h3>${esc(item.title)}</h3><p>${esc(item.meta)}</p></div><span class="dots"></span><strong>${esc(item.tag)}</strong></div>`).join('')}</div>` : `<div class="grid three">${content.showcase.map((item, index) => `<article class="tile"><div class="thumb t${index}"><span class="chip">${esc(item.tag)}</span></div><h3>${esc(item.title)}</h3><p>${esc(item.meta)}</p></article>`).join('')}</div>`}</div></section>`
    }
    case 'stats':
      return `<section class="section stats"><div class="wrap grid four">${content.stats.map(([value, label]) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join('')}</div></section>`
    case 'testimonials':
      return `<section class="section" id="testimonials"><div class="wrap"><p class="kicker">Kind words</p><h2>Loved by the people we work with</h2><div class="grid three">${content.testimonials.map(([quote, name, role]) => `<figure class="card quote"><blockquote>“${esc(quote)}”</blockquote><figcaption><span class="avatar">${esc(name.charAt(0))}</span><span><b>${esc(name)}</b><small>${esc(role)}</small></span></figcaption></figure>`).join('')}</div></div></section>`
    case 'pricing':
      return `<section class="section alt" id="pricing"><div class="wrap"><p class="kicker">Pricing</p><h2>Simple, transparent pricing</h2><div class="grid three">${content.pricing.map((plan) => `<article class="card plan${plan.featured ? ' featured' : ''}">${plan.featured ? '<span class="badge">Most popular</span>' : ''}<h3>${esc(plan.name)}</h3><p class="price">${esc(plan.price)}<small>${esc(plan.period)}</small></p><ul>${plan.features.map((feature) => `<li>${esc(feature)}</li>`).join('')}</ul><a class="btn ${plan.featured ? 'primary' : 'ghost'}" href="#">${esc(spec.cta)}</a></article>`).join('')}</div></div></section>`
    case 'faq':
      return `<section class="section" id="faq"><div class="wrap narrow"><p class="kicker">FAQ</p><h2>Questions, answered</h2>${content.faq.map(([question, answer], index) => `<details${index === 0 ? ' open' : ''}><summary>${esc(question)}</summary><p>${esc(answer)}</p></details>`).join('')}</div></section>`
    case 'contact':
      return `<section class="section alt" id="contact"><div class="wrap split"><div><p class="kicker">Get in touch</p><h2>Let’s make something together</h2><p class="lead">Tell us a little about what you have in mind. We reply to every message within one business day.</p></div><form class="card form" onsubmit="event.preventDefault();this.querySelector('button').textContent='Message sent ✓'"><label>Name<input placeholder="Your name" required></label><label>Email<input type="email" placeholder="you@example.com" required></label><label>Message<textarea rows="4" placeholder="How can we help?"></textarea></label><button class="btn primary" type="submit">Send message</button></form></div></section>`
    case 'cta':
      return `<section class="section"><div class="wrap"><div class="cta"><h2>Ready when you are</h2><p>Join thousands who chose ${esc(spec.name)}. It takes less than a minute to get started.</p><a class="btn light" href="#">${esc(spec.cta)}</a></div></div></section>`
  }
}

export function renderSite(spec: SiteSpec): string {
  const content = CONTENT[spec.kind]
  const [primary, accent] = PALETTES[spec.palette]
  const font = FONTS[spec.style]
  const bg = spec.dark ? '#0b0b0f' : '#ffffff'
  const fg = spec.dark ? '#f4f4f5' : '#0f0f12'
  const muted = spec.dark ? '#a1a1aa' : '#5b5b66'
  const alt = spec.dark ? '#121218' : '#f7f7f8'
  const card = spec.dark ? '#16161d' : '#ffffff'
  const line = spec.dark ? 'rgba(255,255,255,.09)' : 'rgba(15,15,18,.08)'
  const heading = spec.style === 'bold' ? 'letter-spacing:-.02em;text-transform:none' : spec.style === 'elegant' ? 'letter-spacing:-.02em;font-weight:500' : 'letter-spacing:-.035em'

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(spec.name)} — ${esc(content.label)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=${font.query}&display=swap" rel="stylesheet">
<style>
:root{--p:${primary};--a:${accent};--bg:${bg};--fg:${fg};--muted:${muted};--alt:${alt};--card:${card};--line:${line};--r:${spec.radius}px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 ${font.body};-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}h1,h2,h3{font-family:${font.heading};line-height:1.08;margin:0;${heading}}
.wrap{width:min(1120px,calc(100% - 40px));margin:auto}.narrow{width:min(760px,calc(100% - 40px))}
nav{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 82%,transparent);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
nav .wrap{height:68px;display:flex;align-items:center;gap:32px}.logo{font:700 19px ${font.heading};display:flex;align-items:center;gap:9px}.logo i{width:26px;height:26px;border-radius:calc(var(--r)/2 + 2px);background:linear-gradient(135deg,var(--p),var(--a))}
nav ul{display:flex;gap:26px;list-style:none;margin:0 auto 0 0;padding:0;color:var(--muted);font-size:14px}nav ul a:hover{color:var(--fg)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:46px;padding:0 22px;border-radius:calc(var(--r) * .8);font-weight:600;font-size:15px;transition:transform .2s,box-shadow .2s;border:1px solid transparent;cursor:pointer;font-family:inherit}
.btn:hover{transform:translateY(-1px)}.btn.primary{background:var(--p);color:#fff;box-shadow:0 10px 30px -10px var(--p)}.btn.ghost{border-color:var(--line);background:var(--card)}.btn.light{background:#fff;color:#111}.btn.small{height:38px;padding:0 16px;font-size:14px}
.hero{position:relative;overflow:hidden;padding:96px 0 88px}.hero:before{content:"";position:absolute;inset:-30% -10% auto;height:620px;background:radial-gradient(closest-side,color-mix(in srgb,var(--p) 26%,transparent),transparent),radial-gradient(closest-side at 80% 40%,color-mix(in srgb,var(--a) 22%,transparent),transparent);filter:blur(20px);z-index:-1}
.hero .wrap{display:grid;grid-template-columns:1.05fr .95fr;gap:56px;align-items:center}.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:6px 14px 6px 8px;border:1px solid var(--line);border-radius:99px;background:var(--card);font-size:13px;color:var(--muted)}.eyebrow b{width:8px;height:8px;border-radius:50%;background:var(--a);box-shadow:0 0 0 4px color-mix(in srgb,var(--a) 22%,transparent)}
h1{font-size:clamp(42px,6vw,72px);margin:22px 0}.lead{font-size:19px;color:var(--muted);max-width:560px}.actions{display:flex;gap:12px;margin-top:32px;flex-wrap:wrap}
.mock{border:1px solid var(--line);border-radius:calc(var(--r) + 4px);background:var(--card);box-shadow:0 40px 80px -30px rgba(0,0,0,.35);overflow:hidden}.mock-bar{height:38px;display:flex;align-items:center;gap:6px;padding:0 14px;border-bottom:1px solid var(--line)}.mock-bar i{width:10px;height:10px;border-radius:50%;background:var(--line)}.mock-bar span{margin-left:12px;font-size:12px;color:var(--muted)}
.mock-body{display:grid;grid-template-columns:70px 1fr;min-height:300px}.mock-body aside{border-right:1px solid var(--line);padding:16px;display:grid;gap:12px;align-content:start}.mock-body aside b{height:10px;border-radius:5px;background:var(--line)}.mock-body aside b:first-child{background:var(--p)}.mock-body>div{padding:18px}
.mock-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.mock-cards div{border:1px solid var(--line);border-radius:var(--r);padding:12px}.mock-cards small{display:block;color:var(--muted);font-size:11px}.mock-cards strong{font-size:22px}
.mock-chart{height:150px;margin-top:16px;display:flex;align-items:flex-end;gap:10px;padding:14px;border:1px solid var(--line);border-radius:var(--r)}.mock-chart span{flex:1;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,var(--a),var(--p))}
.art{position:relative;aspect-ratio:1/1.02}.art-main{position:absolute;inset:0 8% 6% 0;border-radius:calc(var(--r) * 2);background:radial-gradient(circle at 30% 25%,color-mix(in srgb,var(--a) 70%,#fff),transparent 55%),linear-gradient(150deg,var(--p),color-mix(in srgb,var(--p) 50%,#000));display:flex;flex-direction:column;justify-content:flex-end;padding:30px;color:#fff;box-shadow:0 40px 80px -30px rgba(0,0,0,.4)}.art-main span{font-size:12px;opacity:.8;text-transform:uppercase;letter-spacing:.14em}.art-main strong{font:600 30px ${font.heading}}
.art-float{position:absolute;background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:14px 18px;box-shadow:0 20px 40px -20px rgba(0,0,0,.3)}.art-float small{display:block;color:var(--muted);font-size:12px}.art-float strong{font-size:22px}.art-float.one{right:0;top:12%}.art-float.two{left:-4%;bottom:0}
.logos{border-block:1px solid var(--line);padding:26px 0}.logos .wrap{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;color:var(--muted);font:600 15px ${font.heading};opacity:.7}
.section{padding:96px 0}.section.alt{background:var(--alt)}.kicker{color:var(--p);font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:.14em;margin:0 0 12px}h2{font-size:clamp(32px,4vw,48px);max-width:720px;margin-bottom:48px}
.grid{display:grid;gap:20px}.three{grid-template-columns:repeat(3,1fr)}.four{grid-template-columns:repeat(4,1fr)}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:28px}.feature .icon{width:46px;height:46px;border-radius:calc(var(--r) * .8);display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,var(--p),var(--a));margin-bottom:22px;font-size:18px}.feature h3,.tile h3,.plan h3{font-size:21px;margin-bottom:8px}.feature p,.tile p{color:var(--muted);margin:0}
.thumb{aspect-ratio:4/3;border-radius:var(--r);margin-bottom:18px;position:relative;overflow:hidden;background:linear-gradient(135deg,var(--p),var(--a))}.thumb:after{content:"";position:absolute;width:70%;aspect-ratio:1;border-radius:50%;right:-15%;bottom:-25%;background:rgba(255,255,255,.18)}.thumb.t1{background:linear-gradient(200deg,var(--a),color-mix(in srgb,var(--p) 60%,#000))}.thumb.t2{background:linear-gradient(20deg,color-mix(in srgb,var(--p) 40%,#fff),var(--p))}.chip{position:absolute;left:14px;top:14px;z-index:1;background:rgba(255,255,255,.92);color:#111;font-size:12px;font-weight:600;padding:5px 11px;border-radius:99px}
.menu{display:grid;gap:26px;max-width:760px}.menu-item{display:flex;align-items:baseline;gap:16px}.menu-item h3{font-size:24px}.menu-item p{margin:4px 0 0;color:var(--muted)}.dots{flex:1;border-bottom:1px dashed var(--line)}.menu-item strong{font:600 22px ${font.heading};color:var(--p)}
.stats{padding:64px 0;background:linear-gradient(135deg,var(--p),color-mix(in srgb,var(--p) 55%,var(--a)));color:#fff}.stats strong{display:block;font:700 44px ${font.heading};letter-spacing:-.03em}.stats span{opacity:.82}
.quote blockquote{margin:0 0 24px;font-size:17px}figcaption{display:flex;align-items:center;gap:12px}.avatar{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;color:#fff;font-weight:700;background:linear-gradient(135deg,var(--p),var(--a))}figcaption span:last-child{display:flex;flex-direction:column}figcaption small{color:var(--muted)}
.plan{position:relative;display:flex;flex-direction:column}.plan.featured{border:2px solid var(--p);box-shadow:0 30px 60px -30px var(--p)}.badge{position:absolute;top:-13px;left:28px;background:var(--p);color:#fff;font-size:12px;font-weight:600;padding:4px 12px;border-radius:99px}.price{font:700 44px ${font.heading};letter-spacing:-.03em;margin:8px 0 18px}.price small{font:400 15px ${font.body};color:var(--muted);margin-left:4px}.plan ul{list-style:none;padding:0;margin:0 0 28px;display:grid;gap:10px;flex:1}.plan li:before{content:"✓";color:var(--p);font-weight:700;margin-right:10px}
details{border-bottom:1px solid var(--line);padding:22px 0}summary{cursor:pointer;font-weight:600;font-size:18px;list-style:none;display:flex;justify-content:space-between}summary:after{content:"+";color:var(--p);font-size:24px;line-height:1}details[open] summary:after{content:"–"}details p{color:var(--muted);margin:12px 0 0}
.split{display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:start}.form{display:grid;gap:16px}.form label{display:grid;gap:6px;font-size:14px;font-weight:600}.form input,.form textarea{font:inherit;padding:12px 14px;border:1px solid var(--line);border-radius:calc(var(--r) * .7);background:var(--bg);color:var(--fg);outline:none}.form input:focus,.form textarea:focus{border-color:var(--p);box-shadow:0 0 0 4px color-mix(in srgb,var(--p) 16%,transparent)}
.cta{border-radius:calc(var(--r) * 2);padding:72px 40px;text-align:center;color:#fff;background:radial-gradient(circle at 20% 0,color-mix(in srgb,var(--a) 75%,transparent),transparent 50%),linear-gradient(135deg,var(--p),color-mix(in srgb,var(--p) 50%,#000))}.cta h2{margin:0 auto 14px}.cta p{opacity:.85;max-width:520px;margin:0 auto 30px;font-size:18px}
footer{border-top:1px solid var(--line);padding:40px 0;color:var(--muted);font-size:14px}footer .wrap{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}
@media (max-width:860px){nav ul{display:none}.hero{padding:64px 0}.hero .wrap,.split{grid-template-columns:1fr}.three{grid-template-columns:1fr}.four{grid-template-columns:1fr 1fr}.section{padding:72px 0}.art{max-width:440px}}
</style>
</head>
<body>
<nav><div class="wrap"><a class="logo" href="#"><i></i>${esc(spec.name)}</a><ul>${content.nav.map((item) => `<li><a href="#">${esc(item)}</a></li>`).join('')}</ul><a class="btn primary small" href="#">${esc(spec.cta)}</a></div></nav>
<header class="hero"><div class="wrap"><div><span class="eyebrow"><b></b>${esc(content.eyebrow)}</span><h1>${esc(spec.headline)}</h1><p class="lead">${esc(spec.subheadline)}</p><div class="actions"><a class="btn primary" href="#">${esc(spec.cta)} →</a><a class="btn ghost" href="#showcase">${esc(content.secondary)}</a></div></div>${heroVisual(spec)}</div></header>
${spec.kind === 'saas' || spec.kind === 'agency' ? `<div class="logos"><div class="wrap"><span>Northwind</span><span>Lumen</span><span>Brightline</span><span>Halcyon</span><span>Atlas</span><span>Verdant</span></div></div>` : ''}
${spec.sections.map((section) => renderSection(spec, section)).join('\n')}
<footer><div class="wrap"><span>© ${new Date().getFullYear()} ${esc(spec.name)}. All rights reserved.</span><span>${content.nav.map(esc).join(' · ')}</span></div></footer>
</body>
</html>`
}

export function describeSpec(spec: SiteSpec): string[] {
  return [
    `${kindLabel(spec.kind)} layout with ${spec.sections.length} sections`,
    `${spec.style.charAt(0).toUpperCase() + spec.style.slice(1)} typography on a ${spec.dark ? 'dark' : 'light'} canvas`,
    `${spec.palette.charAt(0).toUpperCase() + spec.palette.slice(1)} palette with matching accents`,
    'Responsive across desktop, tablet, and mobile',
  ]
}

export const TEMPLATE_PROMPTS: { title: string; prompt: string; kind: SiteKind }[] = [
  { title: 'Flowstate', prompt: 'A modern SaaS landing page for a project management startup called "Flowstate" with pricing', kind: 'saas' },
  { title: 'Ember & Oak', prompt: 'An elegant restaurant website called "Ember & Oak" with a menu and reservations', kind: 'restaurant' },
  { title: 'Ava Lindqvist', prompt: 'A minimal black and white portfolio for a photographer named "Ava Lindqvist"', kind: 'portfolio' },
  { title: 'Hearth Goods', prompt: 'A calm online store for handmade home goods called "Hearth Goods"', kind: 'store' },
  { title: 'Forge Athletics', prompt: 'A bold dark gym website called "Forge Athletics" with class pricing', kind: 'fitness' },
  { title: 'Frontier Summit', prompt: 'A playful conference website for "Frontier Summit" with speakers and tickets', kind: 'event' },
]
