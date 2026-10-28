// Applies a visual edit to one JSX element, located by its opening tag's line and column.
// Reads {source, line, column, text?, className?} as JSON on stdin; writes {source} or {error}.
// It only parses the file; generated code is never executed here.
import { parse } from '@babel/parser'
import MagicString from 'magic-string'

function walk(node, visit) {
  if (!node || typeof node.type !== 'string') return
  visit(node)
  for (const key of Object.keys(node)) {
    if (key === 'loc') continue
    const value = node[key]
    if (Array.isArray(value)) value.forEach((child) => walk(child, visit))
    else if (value && typeof value.type === 'string') walk(value, visit)
  }
}

function jsxText(text) {
  return /[{}<>]/.test(text) || text !== text.trim() ? `{${JSON.stringify(text)}}` : text
}

function run(input) {
  const { source, line, column, text, className } = input
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] })
  let element
  walk(ast.program, (node) => {
    const start = node.type === 'JSXElement' && node.openingElement.loc.start
    if (start && start.line === line && start.column === column) element = node
  })
  if (!element) return { error: 'The selected element no longer exists at that location. Refresh the preview and select it again.' }
  const s = new MagicString(source)

  if (typeof text === 'string') {
    const children = element.children
    const meaningful = children.filter((c) => !(c.type === 'JSXText' && !c.value.trim()))
    const simple =
      meaningful.length > 0 &&
      meaningful.every((c) => c.type === 'JSXText' || (c.type === 'JSXExpressionContainer' && c.expression.type === 'StringLiteral'))
    if (!simple) return { error: 'This element contains other elements or computed values. Select the inner text element, or edit it in the Files tab.' }
    s.overwrite(children[0].start, children[children.length - 1].end, jsxText(text))
  }

  if (typeof className === 'string') {
    const opening = element.openingElement
    const attr = opening.attributes.find((a) => a.type === 'JSXAttribute' && (a.name.name === 'className' || a.name.name === 'class'))
    const value = JSON.stringify(className)
    if (!attr) s.appendLeft(opening.name.end, ` className=${value}`)
    else if (attr.value && attr.value.type === 'StringLiteral') s.overwrite(attr.value.start, attr.value.end, value)
    else return { error: 'This element’s styles are computed in code. Edit them in the Files tab.' }
  }
  return { source: s.toString() }
}

let raw = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => (raw += chunk))
process.stdin.on('end', () => {
  try {
    process.stdout.write(JSON.stringify(run(JSON.parse(raw))))
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: `Could not parse the file: ${error.message}` }))
  }
})
