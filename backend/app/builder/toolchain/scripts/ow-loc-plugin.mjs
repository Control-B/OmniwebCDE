// Preview-only Vite plugin: tags JSX elements with their source location so the visual
// editor can map a click in the preview back to a line in the repository.
import { parse } from '@babel/parser'
import MagicString from 'magic-string'
import path from 'node:path'

function walk(node, visit) {
  if (!node || typeof node.type !== 'string') return
  visit(node)
  for (const key of Object.keys(node)) {
    if (key === 'loc' || key === 'start' || key === 'end') continue
    const value = node[key]
    if (Array.isArray(value)) value.forEach((child) => walk(child, visit))
    else if (value && typeof value.type === 'string') walk(value, visit)
  }
}

export function owLoc({ root, native = false }) {
  return {
    name: 'omniweb-source-locations',
    enforce: 'pre',
    transform(code, id) {
      const file = id.split('?')[0]
      if (!/\.(t|j)sx$/.test(file) || file.includes('/node_modules/') || !file.startsWith(root)) return null
      let ast
      try {
        ast = parse(code, { sourceType: 'module', plugins: ['jsx', 'typescript'] })
      } catch {
        return null
      }
      const rel = path.relative(root, file)
      const s = new MagicString(code)
      walk(ast.program, (node) => {
        if (node.type !== 'JSXOpeningElement' || node.name.type !== 'JSXIdentifier') return
        const name = node.name.name
        const loc = `${rel}:${node.loc.start.line}:${node.loc.start.column}`
        if (native) {
          if (name === 'Text' || name === 'View' || name === 'Pressable') s.appendLeft(node.name.end, ` dataSet={{ owLoc: ${JSON.stringify(loc)} }}`)
        } else if (/^[a-z]/.test(name)) {
          s.appendLeft(node.name.end, ` data-ow-loc=${JSON.stringify(loc)}`)
        }
      })
      return { code: s.toString(), map: s.generateMap({ hires: true }) }
    },
  }
}
