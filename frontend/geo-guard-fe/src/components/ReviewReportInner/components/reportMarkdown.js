import { createMd } from '@/utils/md.js'

export function extractTocFromMarkdown(markdown = '') {
  const lines = markdown.split('\n')
  const toc = []
  let chapterIndex = 0

  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/)
    if (!headingMatch) continue
    chapterIndex += 1
    toc.push({
      id: `report-heading-${chapterIndex}`,
      title: headingMatch[2].trim(),
      level: headingMatch[1].length,
    })
  }

  return toc
}

export function parseReportMarkdown(markdown = '') {
  const toc = extractTocFromMarkdown(markdown)
  const md = createMd({ useBreak: true, wrapTable: true })
  let headingCounter = 0
  const originalHeadingOpen = md.renderer.rules.heading_open
    || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))

  md.renderer.rules.heading_open = (tokens, idx, options, env, self) => {
    headingCounter += 1
    tokens[idx].attrSet('id', `report-heading-${headingCounter}`)
    tokens[idx].attrJoin('class', 'report-doc-heading')
    return originalHeadingOpen(tokens, idx, options, env, self)
  }

  return { html: md.render(markdown), toc }
}
