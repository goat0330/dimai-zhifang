import { ref, onScopeDispose } from 'vue'
import * as mars3d from 'mars3d'
import { VectorTile } from '@mapbox/vector-tile'
import Pbf from 'pbf'
import { RISK_GRADE_COLORS } from '@/utils/riskEvaluation.js'
import { getP6DynamicTileUrl } from '@/api/p6Dynamic.js'

const MIN_ZOOM = 7
const MAX_ZOOM = 15
const MAX_VISIBLE_TILES = 64
const GRADE_FIELD = {
  static: 's_grade',
  dynamic: 'r_dynamic_grade',
}

const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

const longitudeToTile = (longitude, zoom) => Math.floor(((longitude + 180) / 360) * (2 ** zoom))

const latitudeToTile = (latitude, zoom) => {
  const safeLatitude = clamp(latitude, -85.05112878, 85.05112878)
  const radians = (safeLatitude * Math.PI) / 180
  return Math.floor(((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2) * (2 ** zoom))
}

const gradeValue = (value) => {
  const match = String(value ?? '').trim().match(/^[A-Z]?([1-5])$/i)
  return match ? Number(match[1]) : null
}

/** Load only the visible P6 vector tiles and draw their clipped slope-unit polygons on Mars3D. */
export function useP6SlopeUnitLayer(onSelect) {
  const rendering = ref(false)
  let map = null
  let viewer = null
  let layers = []
  let visible = true
  let riskMode = 'dynamic'
  let activeLevels = [5, 4]
  let snapshotId = ''
  let generation = 0
  let refreshTimer = null
  let cameraChangedHandler = null
  const tileCache = new Map()

  const clearLayers = () => {
    layers.forEach((layer) => map?.removeLayer(layer, true))
    layers = []
  }

  const getViewZoom = () => {
    const camera = viewer?.camera
    const canvasHeight = viewer?.canvas?.clientHeight || 720
    const height = camera?.positionCartographic?.height || 320000
    const latitude = camera?.positionCartographic?.latitude || 0
    const fovy = camera?.frustum?.fovy || Math.PI / 3
    const metersPerPixel = (2 * height * Math.tan(fovy / 2)) / canvasHeight
    const zoom = Math.log2((156543.03392 * Math.max(0.1, Math.cos(latitude))) / Math.max(metersPerPixel, 1))
    return clamp(Math.round(zoom), MIN_ZOOM, MAX_ZOOM)
  }

  const getVisibleTiles = () => {
    if (!viewer) return []
    const zoom = getViewZoom()
    const rectangle = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid)
    const bounds = rectangle
      ? {
          west: (rectangle.west * 180) / Math.PI,
          south: (rectangle.south * 180) / Math.PI,
          east: (rectangle.east * 180) / Math.PI,
          north: (rectangle.north * 180) / Math.PI,
        }
      : { west: 110.2, south: 29.9, east: 112.15, north: 31.62 }

    let tileZoom = zoom
    let minX
    let maxX
    let minY
    let maxY
    do {
      const count = 2 ** tileZoom
      minX = clamp(longitudeToTile(bounds.west, tileZoom), 0, count - 1)
      maxX = clamp(longitudeToTile(bounds.east, tileZoom), 0, count - 1)
      minY = clamp(latitudeToTile(bounds.north, tileZoom), 0, count - 1)
      maxY = clamp(latitudeToTile(bounds.south, tileZoom), 0, count - 1)
      if ((maxX - minX + 1) * (maxY - minY + 1) <= MAX_VISIBLE_TILES || tileZoom <= MIN_ZOOM) break
      tileZoom -= 1
    } while (tileZoom >= MIN_ZOOM)

    const tiles = []
    for (let x = minX; x <= maxX; x += 1) {
      for (let y = minY; y <= maxY; y += 1) tiles.push({ z: tileZoom, x, y })
    }
    return tiles
  }

  const readTile = async ({ z, x, y }, retry = true) => {
    const key = `${snapshotId}:${z}/${x}/${y}`
    if (tileCache.has(key)) return tileCache.get(key)

    const urlTemplate = getP6DynamicTileUrl({ scenario: 'dynamic', snapshotId })
    const url = urlTemplate.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y))
    const response = await fetch(url)
    if (response.status === 204) return []
    if (response.status === 409 && retry) {
      tileCache.clear()
      snapshotId = ''
      return readTile({ z, x, y }, false)
    }
    if (!response.ok) throw new Error(`斜坡单元瓦片读取失败（${response.status}）`)

    const bytes = new Uint8Array(await response.arrayBuffer())
    const tile = new VectorTile(new Pbf(bytes))
    const layer = tile.layers.p6_dynamic_latest
    if (!layer) return []
    const features = []
    for (let index = 0; index < layer.length; index += 1) {
      const feature = layer.feature(index).toGeoJSON(x, y, z)
      const properties = feature.properties || {}
      const id = String(properties.slope_unit_id || properties.slopeUnitId || '')
      if (!id || !feature.geometry) continue
      features.push({
        ...feature,
        id: `${z}/${x}/${y}/${id}`,
        properties: { ...properties, slopeUnitId: id },
      })
    }
    tileCache.set(key, features)
    if (tileCache.size > 96) tileCache.delete(tileCache.keys().next().value)
    return features
  }

  const drawVisibleTiles = async () => {
    const currentGeneration = ++generation
    if (!map || !viewer || !visible) {
      clearLayers()
      return
    }
    rendering.value = true
    try {
      const visibleTiles = getVisibleTiles()
      const tileFeatures = await Promise.all(visibleTiles.map((tile) => readTile(tile)))
      if (currentGeneration !== generation || !map || !visible) return

      const field = GRADE_FIELD[riskMode]
      const featuresByGrade = new Map()
      tileFeatures.flat().forEach((feature) => {
        const grade = gradeValue(feature.properties?.[field])
        if (grade === null || !activeLevels.includes(grade)) return
        if (!featuresByGrade.has(grade)) featuresByGrade.set(grade, [])
        featuresByGrade.get(grade).push(feature)
      })

      clearLayers()
      featuresByGrade.forEach((features, grade) => {
        const layer = new mars3d.layer.GeoJsonLayer({
          name: riskMode === 'static' ? `斜坡单元易发性${grade}` : `斜坡单元动态风险${grade}`,
          data: { type: 'FeatureCollection', features },
          symbol: {
            styleOptions: {
              color: RISK_GRADE_COLORS[grade],
              opacity: 0.52,
              outline: true,
              outlineColor: RISK_GRADE_COLORS[grade],
              outlineWidth: 0.8,
              clampToGround: true,
            },
          },
        })
        layer.on(mars3d.EventType.click, (event) => {
          const properties = event?.graphic?.attr || {}
          onSelect?.({ ...properties, slopeUnitId: properties.slope_unit_id || properties.slopeUnitId })
        })
        map.addLayer(layer)
        layers.push(layer)
      })
    } catch (error) {
      if (currentGeneration === generation) {
        clearLayers()
        console.error('加载宜昌斜坡单元失败', error)
      }
    } finally {
      if (currentGeneration === generation) rendering.value = false
    }
  }

  const scheduleRefresh = () => {
    window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(() => void drawVisibleTiles(), 300)
  }

  const attach = (nextMap) => {
    if (viewer && cameraChangedHandler) viewer.camera.changed.removeEventListener(cameraChangedHandler)
    clearLayers()
    map = nextMap || null
    viewer = map?.viewer || null
    if (!viewer) return
    cameraChangedHandler = scheduleRefresh
    viewer.camera.changed.addEventListener(cameraChangedHandler)
    scheduleRefresh()
  }

  const setStyle = ({ mode, levels, nextSnapshotId } = {}) => {
    if (mode === 'static' || mode === 'dynamic') riskMode = mode
    if (Array.isArray(levels)) activeLevels = levels.map(Number).filter((level) => level >= 1 && level <= 5)
    if (nextSnapshotId && nextSnapshotId !== snapshotId) {
      snapshotId = nextSnapshotId
      tileCache.clear()
    }
    scheduleRefresh()
  }

  const setVisible = (nextVisible) => {
    visible = Boolean(nextVisible)
    if (visible) scheduleRefresh()
    else {
      generation += 1
      rendering.value = false
      clearLayers()
    }
  }

  const destroy = () => {
    window.clearTimeout(refreshTimer)
    if (viewer && cameraChangedHandler) viewer.camera.changed.removeEventListener(cameraChangedHandler)
    generation += 1
    clearLayers()
    viewer = null
    map = null
  }

  onScopeDispose(destroy)
  return { attach, setStyle, setVisible, rendering, refresh: scheduleRefresh }
}
