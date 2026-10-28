// The rules of the interface standard that a machine can verify. Run with `npm run check`.
// Each finding names the file, the line and the rule in docs/ it breaks. Exit code 1 when anything is found.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const src = path.join(root, 'src')
const rules = JSON.parse(fs.readFileSync(path.join(root, 'checks', 'rules.json'), 'utf8'))
const findings = []
const report = (rule, file, line, message) => findings.push({ rule, file: path.relative(root, file).replaceAll('\\', '/'), line, message })

const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.join(dir, entry.name)]))
const files = walk(src)
const rel = (file) => path.relative(src, file).replaceAll('\\', '/')
const lineOf = (text, index) => text.slice(0, index).split('\n').length
const withoutComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ' '))

// 1. Colours and text sizes are written once, in tokens.css.
for (const file of files.filter((name) => name.endsWith('.css') && rel(name) !== 'tokens.css')) {
  const css = withoutComments(fs.readFileSync(file, 'utf8'))
  for (const match of css.matchAll(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g)) report('tokens', file, lineOf(css, match.index), `Raw colour "${match[0]}". Use a variable from tokens.css (docs/01-nen-tang.md).`)
  for (const match of css.matchAll(/font-size:\s*[\d.]+(px|rem|em)/g)) report('tokens', file, lineOf(css, match.index), `Raw text size "${match[0]}". Use one of the --text-* variables (docs/01-nen-tang.md).`)
}

// Page and gallery stylesheets lay out their own classes; they never restyle a component from outside.
for (const file of files.filter((name) => /^(pages|gallery)\/.*\.css$/.test(rel(name)))) {
  const css = withoutComments(fs.readFileSync(file, 'utf8'))
  for (const match of css.matchAll(/\.(ui|shell)-[\w-]+/g)) report('components', file, lineOf(css, match.index), `The page stylesheet styles the component class "${match[0]}". Change the component in src/ui, or wrap it in an element of your own.`)
}

// 2 to 4 read the code as a syntax tree, so comments and code that merely looks like text are not flagged.
const hasWords = (text) => /\p{L}{2,}/u.test(text)
const allowedText = new Set(rules.allowedLiteralText)
const controlTags = new Set(['button', 'input', 'select', 'textarea', 'dialog', 'table'])
const textProps = new Set(['label', 'title', 'text', 'help', 'error', 'hint', 'placeholder', 'alt', 'aria-label', 'confirmLabel', 'cancelLabel', 'note'])
const isScreen = (name) => /^(pages|gallery|app)\//.test(name)
const usedKeys = new Set()
const keyPrefixes = new Set()

for (const file of files.filter((name) => /\.tsx?$/.test(name) && !rel(name).startsWith('i18n/'))) {
  const name = rel(file)
  const text = fs.readFileSync(file, 'utf8')
  const tree = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const line = (node) => tree.getLineAndCharacterOfPosition(node.getStart()).line + 1
  const visit = (node) => {
    // 2. No raw colours in code either, except in the one file that defines the brand.
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && name !== 'brand.ts' && /^#[0-9a-fA-F]{3,8}$|^rgba?\(|^hsla?\(/.test(node.text)) {
      report('tokens', file, line(node), `Raw colour "${node.text}" in code. Use a variable from tokens.css.`)
    }
    // Message keys in use, for the dictionary check below.
    if (ts.isStringLiteral(node) && /^[a-z][\w]*(\.[\w]+)+$/.test(node.text)) usedKeys.add(node.text)
    if (ts.isTemplateExpression(node) && /^[a-z][\w]*(\.[\w]+)*\.$/.test(node.head.text)) keyPrefixes.add(node.head.text)

    // 3. Words on screen come from the dictionaries, never from the code. Sample data in app/store.tsx is data.
    if (name !== 'app/store.tsx') {
      // A token name such as --text-md is a name, not a word.
      if (ts.isJsxText(node) && hasWords(node.text) && !allowedText.has(node.text.trim()) && !/^--[\w-]*$/.test(node.text.trim())) {
        report('words', file, line(node), `Text "${node.text.trim().slice(0, 50)}" is written in the code. Add a key to i18n/vi.ts and i18n/en.ts and use t() (docs/04-cach-viet.md).`)
      }
      if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer) && textProps.has(node.name.getText()) && hasWords(node.initializer.text)) {
        report('words', file, line(node), `${node.name.getText()}="${node.initializer.text.slice(0, 50)}" is written in the code. Use t() (docs/04-cach-viet.md).`)
      }
    }

    // 4. Screens are assembled from the component set; they do not build their own controls or reach into its classes.
    if (isScreen(name)) {
      if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && controlTags.has(node.tagName.getText())) {
        report('components', file, line(node), `<${node.tagName.getText()}> used directly in a screen. Use the component from src/ui (docs/02-thanh-phan.md).`)
      }
      if (ts.isJsxAttribute(node) && node.name.getText() === 'className' && node.initializer && /\b(ui|shell)-/.test(node.initializer.getText())) {
        report('components', file, line(node), `A screen uses the internal class ${node.initializer.getText().slice(0, 40)}. Use the component, or add what is missing to src/ui.`)
      }
      if (ts.isJsxAttribute(node) && node.name.getText() === 'style' && !name.startsWith('gallery/')) {
        report('components', file, line(node), 'Inline style in a screen. Put layout in the page stylesheet and looks in src/ui.')
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(tree)
}

// 5. Both dictionaries have the same keys, every key is used, and every key used exists.
const keysOf = (file) => [...fs.readFileSync(path.join(src, 'i18n', file), 'utf8').matchAll(/^\s*'([\w.]+)':\s*(['"])((?:\\.|(?!\2).)*)\2,?\s*$/gm)].map((match) => ({ key: match[1], text: match[3].replace(/\\'/g, "'"), index: match.index }))
const dictionaries = { 'vi.ts': keysOf('vi.ts'), 'en.ts': keysOf('en.ts') }
const names = Object.fromEntries(Object.entries(dictionaries).map(([file, entries]) => [file, new Set(entries.map((entry) => entry.key))]))
for (const [file, other] of [['vi.ts', 'en.ts'], ['en.ts', 'vi.ts']]) {
  const text = fs.readFileSync(path.join(src, 'i18n', file), 'utf8')
  for (const entry of dictionaries[file]) {
    if (!names[other].has(entry.key)) report('dictionaries', path.join(src, 'i18n', file), lineOf(text, entry.index), `"${entry.key}" is missing from ${other}.`)
    if (file === 'vi.ts' && !usedKeys.has(entry.key) && ![...keyPrefixes].some((prefix) => entry.key.startsWith(prefix))) report('dictionaries', path.join(src, 'i18n', file), lineOf(text, entry.index), `"${entry.key}" is not used anywhere. Remove it from both dictionaries.`)
    // The same placeholders in both languages.
    const twin = dictionaries[other].find((candidate) => candidate.key === entry.key)
    // A message with a singular and a plural form names each placeholder once per form; compare the names, not the count.
    const holes = (value) => [...new Set([...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]))].sort().join(',')
    if (file === 'vi.ts' && twin && holes(twin.text) !== holes(entry.text)) report('dictionaries', path.join(src, 'i18n', file), lineOf(text, entry.index), `"${entry.key}" has different {placeholders} in the two languages.`)
    // 6. Words the standard keeps off the screen.
    for (const word of rules.bannedWords[file.slice(0, 2)]) {
      if (new RegExp(`(^|[^\\p{L}])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\p{L}])`, 'iu').test(entry.text)) report('words', path.join(src, 'i18n', file), lineOf(text, entry.index), `"${entry.key}" shows the word "${word}" (docs/04-cach-viet.md).`)
    }
    if (/[.]$/.test(entry.text) && entry.text.length < 28 && !/[.!?…].*[.]$/.test(entry.text) && !entry.text.includes(' ')) report('words', path.join(src, 'i18n', file), lineOf(text, entry.index), `"${entry.key}" is a one-word label ending in a full stop.`)
  }
}

if (findings.length === 0) {
  console.log(`Interface standard: no findings in ${files.length} files, ${dictionaries['vi.ts'].length} messages in 2 languages.`)
} else {
  const order = ['tokens', 'components', 'words', 'dictionaries']
  for (const finding of findings.sort((a, b) => order.indexOf(a.rule) - order.indexOf(b.rule) || a.file.localeCompare(b.file) || a.line - b.line)) console.log(`[${finding.rule}] ${finding.file}:${finding.line}  ${finding.message}`)
  console.log(`\n${findings.length} finding(s). The rules are explained in docs/.`)
  process.exit(1)
}
