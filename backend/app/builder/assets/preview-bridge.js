// Injected into every preview page by the preview server. Talks only to the Omniweb builder
// window (origins are listed on the script tag) and only exposes source locations of elements.
;(() => {
  const script = document.currentScript
  const origins = JSON.parse(script?.dataset.origins || '[]')
  const kind = script?.dataset.kind || 'web'
  if (window.parent === window) return
  let selecting = false
  let box = null
  let label = null

  const send = (message) => {
    for (const origin of origins) window.parent.postMessage({ source: 'omniweb-preview', kind, ...message }, origin)
  }

  const located = (target) => (target instanceof Element ? target.closest('[data-ow-loc]') : null)

  const describe = (element) => {
    const rect = element.getBoundingClientRect()
    const textOnly = [...element.childNodes].every((node) => node.nodeType === Node.TEXT_NODE)
    return {
      loc: element.getAttribute('data-ow-loc'),
      tag: element.tagName.toLowerCase(),
      text: textOnly ? element.textContent.trim().slice(0, 500) : null,
      className: kind === 'web' ? element.getAttribute('class') || '' : null,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
    }
  }

  const ensureOverlay = () => {
    if (box) return
    box = document.createElement('div')
    label = document.createElement('div')
    Object.assign(box.style, { position: 'fixed', pointerEvents: 'none', zIndex: 2147483646, border: '2px solid #6d5efc', background: 'rgba(109,94,252,.08)', borderRadius: '3px', display: 'none' })
    Object.assign(label.style, { position: 'fixed', pointerEvents: 'none', zIndex: 2147483647, background: '#6d5efc', color: '#fff', font: '11px/1.6 ui-sans-serif, system-ui', padding: '0 6px', borderRadius: '3px', display: 'none' })
    document.documentElement.append(box, label)
  }

  const highlight = (element) => {
    ensureOverlay()
    if (!element) {
      box.style.display = label.style.display = 'none'
      return
    }
    const rect = element.getBoundingClientRect()
    Object.assign(box.style, { display: 'block', left: `${rect.x - 2}px`, top: `${rect.y - 2}px`, width: `${rect.width + 4}px`, height: `${rect.height + 4}px` })
    label.textContent = element.tagName.toLowerCase()
    Object.assign(label.style, { display: 'block', left: `${rect.x - 2}px`, top: `${Math.max(0, rect.y - 20)}px` })
  }

  document.addEventListener('mouseover', (event) => selecting && highlight(located(event.target)), true)
  document.addEventListener(
    'click',
    (event) => {
      if (!selecting) return
      const element = located(event.target)
      event.preventDefault()
      event.stopPropagation()
      if (element) send({ type: 'selected', element: describe(element) })
    },
    true,
  )

  window.addEventListener('message', (event) => {
    if (!origins.includes(event.origin) || event.source !== window.parent) return
    const data = event.data || {}
    if (data.type === 'omniweb:select') {
      selecting = Boolean(data.enabled)
      document.documentElement.style.cursor = selecting ? 'crosshair' : ''
      if (!selecting) highlight(null)
    } else if (data.type === 'omniweb:navigate' && typeof data.hash === 'string' && data.hash.startsWith('#')) {
      location.hash = data.hash
    } else if (data.type === 'omniweb:reload') {
      location.reload()
    }
  })

  const report = () => send({ type: 'location', hash: location.hash || '#/' })
  window.addEventListener('hashchange', report)
  window.addEventListener('load', report)
  window.addEventListener('error', (event) => send({ type: 'error', message: String(event.message || 'Script error').slice(0, 500) }))
  window.addEventListener('unhandledrejection', (event) => send({ type: 'error', message: String(event.reason?.message || event.reason || 'Unhandled rejection').slice(0, 500) }))
})()
