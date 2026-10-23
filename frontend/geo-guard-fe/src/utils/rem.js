const baseFontSize = 16

function setRem() {
  const width = document.documentElement.clientWidth || window.innerWidth
  const maxFontSize = width <= 1920 ? 20 : width <= 2560 ? 28 : 36
  const fontSize = Math.max(12, Math.min(baseFontSize * (width / 1920), maxFontSize))
  document.documentElement.style.fontSize = `${fontSize}px`
}

setRem()
window.addEventListener('resize', setRem)
