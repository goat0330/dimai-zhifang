const AVATAR_GLYPH_COLORS = ['#0f766e', '#2563eb', '#7c3aed', '#c2410c', '#be123c']

export const AVATAR_BACKGROUND_TOKENS = [
  { background: 'linear-gradient(135deg, var(--main-600), var(--color-info-500))', color: '#fff' },
  {
    background: 'linear-gradient(135deg, var(--chart-palette-5), var(--chart-palette-9))',
    color: '#fff'
  },
  {
    background: 'linear-gradient(135deg, var(--chart-palette-7), var(--chart-palette-3))',
    color: '#fff'
  },
  {
    background: 'linear-gradient(135deg, var(--color-accent-500), var(--chart-palette-6))',
    color: '#fff'
  },
  {
    background: 'linear-gradient(135deg, var(--chart-palette-4), var(--color-error-500))',
    color: '#fff'
  }
]

const normalizeSeed = (id) => {
  if (id === null || id === undefined || String(id).trim() === '') {
    throw new Error('generatePixelAvatar requires an id')
  }
  return String(id).trim()
}

export const generatePixelAvatar = (id) => {
  const seed = normalizeSeed(id)
  let state = 0
  for (const char of seed) state = (state * 31 + char.codePointAt(0)) >>> 0
  const color = AVATAR_GLYPH_COLORS[state % AVATAR_GLYPH_COLORS.length]
  const cells = []
  for (let y = 0; y < 7; y += 1) {
    for (let x = 0; x < 4; x += 1) {
      state = (state * 1664525 + 1013904223) >>> 0
      if ((state & 3) !== 0) {
        cells.push([x, y])
        if (x !== 3) cells.push([6 - x, y])
      }
    }
  }
  const glyph = cells.map(([x, y]) => '<rect x="' + (8 + x * 7) + '" y="' + (8 + y * 7) + '" width="6" height="6" rx="1.5"/>').join('')
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#f1f5f9"/><g fill="' + color + '">' + glyph + '</g></svg>'
  return 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg)
}

export const getAvatarInitials = (name, kind = 'user') => {
  const fallback = kind === 'agent' ? '智能' : '用户'
  const normalizedName = String(name || '').trim()
  if (!normalizedName) return fallback
  return Array.from(normalizedName).slice(0, 2).join('')
}

export const getAvatarColorIndex = (seed) => {
  const normalizedSeed = String(seed || '').trim()
  const value = normalizedSeed || 'avatar'
  let hash = 0
  for (const char of value) {
    hash = (hash * 31 + char.codePointAt(0)) >>> 0
  }
  return hash % AVATAR_BACKGROUND_TOKENS.length
}

export const getAvatarFallbackStyle = (seed) => AVATAR_BACKGROUND_TOKENS[getAvatarColorIndex(seed)]
