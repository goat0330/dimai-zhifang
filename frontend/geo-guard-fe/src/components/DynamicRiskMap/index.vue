<template>
  <div ref="mapContainerRef" class="dynamic-risk-map"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import wellknown from 'wellknown'
import { bbox, centerOfMass } from '@turf/turf'
import {
  getDynamicRiskLevelColor,
  normalizeRiskLevel,
  RISK_GRADE_COLORS,
  RISK_GRADE_NAMES,
} from '@/utils/riskEvaluation.js'
import 'maplibre-gl/dist/maplibre-gl.css'

defineOptions({ name: 'DynamicRiskMap' })

const props = defineProps({
  units: {
    type: Array,
    default: () => [],
  },
  preserveDrawingBuffer: Boolean,
  chongqingSlopeStyle: Boolean,
  showYichangBoundary: Boolean,
  interactive: {
    type: Boolean,
    default: true,
  },
  attributionControl: {
    type: Boolean,
    default: true,
  },
  levelField: {
    type: String,
    default: 'dynamicRiskLevel',
  },
  levelColors: {
    type: Object,
    default: () => RISK_GRADE_COLORS,
  },
  riskTypeName: {
    type: String,
    default: '风险',
  },
  activeLevels: {
    type: Array,
    default: () => [5, 4, 3, 2, 1],
  },
  vectorTileUrl: { type: String, default: '' },
  vectorSourceLayer: { type: String, default: 'p6_dynamic_latest' },
})

const emit = defineEmits(['ready'])
const mapContainerRef = ref(null)
let map = null
let popup = null
let hoveredId = null
let resizeObserver = null
let resizeFrame = null
let sourceMode = ''
let activeVectorTileUrl = ''
let activeVectorSourceLayer = ''
const unitLabelMarkers = new Map()

const SOURCE_ID = 'dynamic-risk-units'
const FILL_LAYER_ID = 'dynamic-risk-units-fill'
const LINE_LAYER_ID = 'dynamic-risk-units-line'
const LABEL_LAYER_ID = 'dynamic-risk-units-label'
const BOUNDARY_SOURCE_ID = 'yichang-city-boundary'
const BOUNDARY_GLOW_LAYER_ID = 'yichang-city-boundary-glow'
const BOUNDARY_LINE_LAYER_ID = 'yichang-city-boundary-line'
const CHONGQING_SLOPE_FILL = '#356BFA'
const TDT_TOKEN = import.meta.env.VITE_TDT_TOKEN

const toFeatureCollection = (units, config = {}) => {
  const levelField = config.levelField ?? props.levelField
  const levelColors = config.levelColors ?? props.levelColors
  const activeLevels = config.activeLevels ?? props.activeLevels

  return {
    type: 'FeatureCollection',
    features: units.map((item, index) => {
    let geometry = null
    try {
      geometry = wellknown.parse(item?.wkt || '')
    } catch {
      geometry = null
    }
    if (!geometry) return null
    const riskLevel = normalizeRiskLevel(item?.[levelField] ?? item?.r_grade ?? item?.R?.grade)
    if (riskLevel === null || !activeLevels.includes(riskLevel)) return null
    return {
      type: 'Feature',
      id: String(item?.id ?? item?.slopeUnitId ?? index),
      geometry,
      properties: {
        id: String(item?.id ?? item?.slopeUnitId ?? ''),
        name: String(item?.name || item?.slopeUnitName || item?.slopeName || '').trim(),
        street: item?.street ?? '',
        village: item?.village ?? '',
        area: item?.area ?? '',
        riskLevel,
        riskLevelText: formatActiveGrade(riskLevel, levelField),
        fillColor: levelColors[riskLevel] || getDynamicRiskLevelColor(riskLevel),
      },
    }
  }).filter(Boolean),
  }
}

const vectorColorExpression = (field, colors) => [
  'match', ['get', field],
  ...[1, 2, 3, 4, 5].flatMap((level) => [`${field[0].toUpperCase()}${level}`, colors[level] || getDynamicRiskLevelColor(level)]),
  '#A6ACB8',
]

const vectorLevelFilter = (field, activeLevels) => [
  'in', ['get', field], ['literal', activeLevels.map((level) => `${field[0].toUpperCase()}${level}`)],
]

const formatGrade = (value, suffix) => {
  const match = String(value ?? '').trim().match(/^[A-Z]?([1-5])$/i)
  return match ? `${RISK_GRADE_NAMES[Number(match[1])]}${suffix}` : ''
}

const formatActiveGrade = (level, field) => {
  const gradeName = RISK_GRADE_NAMES[level]
  if (!gradeName) return '--'
  return field === 's_grade' || field.toLowerCase().includes('susceptibility')
    ? `${gradeName}易发性`
    : `${gradeName}风险`
}

const createPopupRow = (label, value) => {
  const row = document.createElement('div')
  row.className = 'risk-popup-row'
  const labelElement = document.createElement('span')
  labelElement.textContent = label
  const valueElement = document.createElement('strong')
  valueElement.textContent = value || '--'
  row.append(labelElement, valueElement)
  return row
}

const createPopupContent = (properties) => {
  const wrapper = document.createElement('div')
  wrapper.className = 'risk-popup'
  const header = document.createElement('div')
  header.className = 'risk-popup-header'
  const title = document.createElement('strong')
  const unitTitle = properties.name || (properties.id ? `${properties.id}号` : '') || '--'
  const formattedTitle = unitTitle.endsWith('斜坡单元') || unitTitle.endsWith('斜坡')
    ? unitTitle
    : `${unitTitle}斜坡单元`
  title.textContent = `${formattedTitle}${props.riskTypeName}详情`
  const tag = document.createElement('span')
  tag.textContent = properties.riskLevelText || '--'
  tag.style.backgroundColor = properties.fillColor || '#A6ACB8'
  header.append(title, tag)
  wrapper.append(header)
  const rows = [
    ['所属县市', properties.county],
    ['当前图层', properties.riskLevelText],
    ['静态易发性', properties.sGrade],
    ['动态危险性', properties.hGrade],
    ['承灾体暴露度', properties.eGrade],
    ['综合暴露指数', properties.eTotal],
    ['动态风险', properties.rGrade],
    ['24小时降雨量', properties.rainfall24h],
  ]
  rows.forEach(([label, value]) => {
    if (value !== undefined && value !== null && value !== '') wrapper.append(createPopupRow(label, String(value)))
  })
  return wrapper
}

const showPopup = (event) => {
  const feature = event.features?.[0]
  if (!feature) return
  map.getCanvas().style.cursor = 'pointer'
  const raw = feature.properties || {}
  const id = raw.slope_unit_id || raw.id || raw.slopeUnitId || ''
  const riskLevel = normalizeRiskLevel(raw[props.levelField] ?? raw.r_grade ?? raw.R?.grade)
  const properties = {
    ...raw,
    id,
    name: raw.name || id,
    riskLevel,
    riskLevelText: formatActiveGrade(riskLevel, props.levelField),
    fillColor: props.levelColors[riskLevel] || getDynamicRiskLevelColor(riskLevel),
    sGrade: formatGrade(raw.s_grade, '易发性'),
    hGrade: formatGrade(raw.h_dynamic_grade, '危险性'),
    eGrade: formatGrade(raw.e_grade, '暴露度'),
    eTotal: raw.E_total !== undefined && raw.E_total !== null && raw.E_total !== ''
      ? Number(raw.E_total).toLocaleString(undefined, { maximumFractionDigits: 2 })
      : '',
    rGrade: formatGrade(raw.r_dynamic_grade, '风险'),
    rainfall24h: Number.isFinite(Number(raw.rain_past24h_mm)) ? `${Number(raw.rain_past24h_mm).toFixed(1)} mm` : '',
  }
  const center = event.lngLat?.toArray?.() || centerOfMass(feature).geometry.coordinates
  popup.setLngLat(center).setDOMContent(createPopupContent(properties)).addTo(map)
}

const clearHover = () => {
  if (hoveredId !== null) {
    map.setFeatureState({ source: SOURCE_ID, ...(sourceMode === 'vector' ? { sourceLayer: activeVectorSourceLayer } : {}), id: hoveredId }, { hover: false })
  }
  hoveredId = null
  map.getCanvas().style.cursor = ''
  popup?.remove()
}

const clearUnitLabels = () => {
  unitLabelMarkers.forEach((marker) => marker.remove())
  unitLabelMarkers.clear()
}

const drawYichangBoundary = () => {
  if (!map || (!props.chongqingSlopeStyle && !props.showYichangBoundary)) return
  if (!map.getSource(BOUNDARY_SOURCE_ID)) {
    map.addSource(BOUNDARY_SOURCE_ID, {
      type: 'geojson',
      data: `${import.meta.env.BASE_URL}geo/yichang/yichang_city_boundary_2022.geojson`,
    })
  }
  if (!map.getLayer(BOUNDARY_GLOW_LAYER_ID)) {
    map.addLayer({
      id: BOUNDARY_GLOW_LAYER_ID,
      type: 'line',
      source: BOUNDARY_SOURCE_ID,
      paint: { 'line-color': '#168BFF', 'line-opacity': 0.72, 'line-width': 7, 'line-blur': 3 },
    })
  }
  if (!map.getLayer(BOUNDARY_LINE_LAYER_ID)) {
    map.addLayer({
      id: BOUNDARY_LINE_LAYER_ID,
      type: 'line',
      source: BOUNDARY_SOURCE_ID,
      paint: { 'line-color': '#DCEDFF', 'line-opacity': 1, 'line-width': 2 },
    })
  }
  map.moveLayer(BOUNDARY_GLOW_LAYER_ID)
  map.moveLayer(BOUNDARY_LINE_LAYER_ID)
}

const clearYichangBoundary = () => {
  if (!map) return
  ;[BOUNDARY_LINE_LAYER_ID, BOUNDARY_GLOW_LAYER_ID].forEach((id) => {
    if (map.getLayer(id)) map.removeLayer(id)
  })
  if (map.getSource(BOUNDARY_SOURCE_ID)) map.removeSource(BOUNDARY_SOURCE_ID)
}

const updateUnitLabels = () => {
  const labelMinZoom = props.chongqingSlopeStyle ? 13 : 15
  if (!map || sourceMode !== 'vector' || map.getZoom() < labelMinZoom || !map.getLayer(FILL_LAYER_ID)) {
    clearUnitLabels()
    return
  }

  const canvas = map.getCanvas()
  const features = map.queryRenderedFeatures({ layers: [FILL_LAYER_ID] })
  const desiredLabels = new Map()
  const labelPoints = []
  features.forEach((feature) => {
    const id = String(feature.properties?.slope_unit_id || '')
    if (!id || desiredLabels.has(id)) return

    const center = centerOfMass(feature).geometry.coordinates
    const point = map.project(center)
    if (point.x < 0 || point.y < 0 || point.x > canvas.clientWidth || point.y > canvas.clientHeight) return
    if (labelPoints.some((other) => Math.hypot(other.x - point.x, other.y - point.y) < 72)) return

    labelPoints.push(point)
    desiredLabels.set(id, center)
  })

  desiredLabels.forEach((center, id) => {
    let marker = unitLabelMarkers.get(id)
    if (!marker) {
      const element = document.createElement('span')
      element.className = 'slope-unit-id-label'
      element.textContent = id
      element.setAttribute('aria-label', `${id}斜坡单元`)
      marker = new maplibregl.Marker({ element, anchor: 'center' })
      unitLabelMarkers.set(id, marker)
    }
    marker.setLngLat(center).addTo(map)
  })

  unitLabelMarkers.forEach((marker, id) => {
    if (desiredLabels.has(id)) return
    marker.remove()
    unitLabelMarkers.delete(id)
  })
}

const updateHover = (event) => {
  const feature = event.features?.[0]
  if (!feature) return
  if (hoveredId !== null) {
    map.setFeatureState({ source: SOURCE_ID, ...(sourceMode === 'vector' ? { sourceLayer: activeVectorSourceLayer } : {}), id: hoveredId }, { hover: false })
  }
  hoveredId = feature.id
  if (hoveredId !== undefined && hoveredId !== null) {
    map.setFeatureState({ source: SOURCE_ID, ...(sourceMode === 'vector' ? { sourceLayer: activeVectorSourceLayer } : {}), id: hoveredId }, { hover: true })
  }
  showPopup(event)
}

const drawUnits = (config, units = props.units) => {
  if (!map?.isStyleLoaded()) return
  const resolvedConfig = (config && !Array.isArray(config) && typeof config === 'object') ? config : {}
  const tileUrl = resolvedConfig.vectorTileUrl ?? props.vectorTileUrl
  const levelField = resolvedConfig.levelField ?? props.levelField
  const levelColors = resolvedConfig.levelColors ?? props.levelColors
  const activeLevels = resolvedConfig.activeLevels ?? props.activeLevels
  const sourceLayer = resolvedConfig.vectorSourceLayer ?? props.vectorSourceLayer

  if (tileUrl) {
    const source = map.getSource(SOURCE_ID)
    if (source && (sourceMode !== 'vector' || activeVectorTileUrl !== tileUrl || activeVectorSourceLayer !== sourceLayer)) {
      map.off('mousemove', FILL_LAYER_ID, updateHover)
      map.off('mouseleave', FILL_LAYER_ID, clearHover)
      map.off('idle', updateUnitLabels)
      clearUnitLabels()
      ;[LABEL_LAYER_ID, LINE_LAYER_ID, FILL_LAYER_ID].forEach((id) => {
        if (map.getLayer(id)) map.removeLayer(id)
      })
      map.removeSource(SOURCE_ID)
      sourceMode = ''
      activeVectorTileUrl = ''
      activeVectorSourceLayer = ''
    }

    if (!map.getSource(SOURCE_ID)) {
      map.addSource(SOURCE_ID, {
        type: 'vector',
        tiles: [tileUrl],
        minzoom: 7,
        maxzoom: 15,
        promoteId: { [sourceLayer]: 'slope_unit_id' },
      })
      sourceMode = 'vector'
      activeVectorTileUrl = tileUrl
      activeVectorSourceLayer = sourceLayer
      map.addLayer({
        id: FILL_LAYER_ID,
        type: 'fill',
        source: SOURCE_ID,
        'source-layer': sourceLayer,
        ...(props.chongqingSlopeStyle ? { minzoom: 7 } : {}),
        filter: props.chongqingSlopeStyle
          ? ['has', 'slope_unit_id']
          : vectorLevelFilter(levelField, activeLevels),
        paint: {
          'fill-color': props.chongqingSlopeStyle
            ? CHONGQING_SLOPE_FILL
            : vectorColorExpression(levelField, levelColors),
          'fill-opacity': props.chongqingSlopeStyle
            ? ['case', ['boolean', ['feature-state', 'hover'], false], 0.72, 0.48]
            : 0.74,
        },
      })
      map.addLayer({
        id: LINE_LAYER_ID,
        type: 'line',
        source: SOURCE_ID,
        'source-layer': sourceLayer,
        minzoom: props.chongqingSlopeStyle ? 7 : 10,
        paint: props.chongqingSlopeStyle
          ? {
              'line-color': '#a9caff',
              'line-dasharray': [2, 3],
              'line-opacity': 0.24,
              'line-width': 0.5,
            }
          : { 'line-color': '#ffffff', 'line-opacity': 0.38, 'line-width': 0.65 },
      })
      map.on('mousemove', FILL_LAYER_ID, updateHover)
      map.on('mouseleave', FILL_LAYER_ID, clearHover)
      map.on('idle', updateUnitLabels)
    } else {
      map.setPaintProperty(FILL_LAYER_ID, 'fill-color', props.chongqingSlopeStyle
        ? CHONGQING_SLOPE_FILL
        : vectorColorExpression(levelField, levelColors))
      map.setFilter(FILL_LAYER_ID, props.chongqingSlopeStyle
        ? ['has', 'slope_unit_id']
        : vectorLevelFilter(levelField, activeLevels))
      map.setLayerZoomRange(FILL_LAYER_ID, props.chongqingSlopeStyle ? 7 : 0, 24)
      map.setLayerZoomRange(LINE_LAYER_ID, props.chongqingSlopeStyle ? 7 : 10, 24)
      map.setPaintProperty(FILL_LAYER_ID, 'fill-opacity', props.chongqingSlopeStyle
        ? ['case', ['boolean', ['feature-state', 'hover'], false], 0.72, 0.48]
        : 0.74)
      if (props.chongqingSlopeStyle) {
        map.setPaintProperty(LINE_LAYER_ID, 'line-color', '#a9caff')
        map.setPaintProperty(LINE_LAYER_ID, 'line-dasharray', [2, 3])
        map.setPaintProperty(LINE_LAYER_ID, 'line-opacity', 0.24)
        map.setPaintProperty(LINE_LAYER_ID, 'line-width', 0.5)
      }
    }
    if (props.chongqingSlopeStyle || props.showYichangBoundary) drawYichangBoundary()
    else clearYichangBoundary()
    return
  }

  if (!Array.isArray(units) && !props.units.length) return
  if (!Array.isArray(units) && units.length === 0 && !map.getSource(SOURCE_ID)) return
  if (map.getSource(SOURCE_ID) && sourceMode === 'vector') {
    map.off('mousemove', FILL_LAYER_ID, updateHover)
    map.off('mouseleave', FILL_LAYER_ID, clearHover)
    map.off('idle', updateUnitLabels)
    clearUnitLabels()
    ;[LABEL_LAYER_ID, LINE_LAYER_ID, FILL_LAYER_ID].forEach((id) => {
      if (map.getLayer(id)) map.removeLayer(id)
    })
    map.removeSource(SOURCE_ID)
    sourceMode = ''
    activeVectorTileUrl = ''
    activeVectorSourceLayer = ''
    clearYichangBoundary()
  }
  const targetUnits = Array.isArray(units) ? units : props.units
  const data = toFeatureCollection(targetUnits, resolvedConfig)
  const source = map.getSource(SOURCE_ID)
  if (source) {
    source.setData(data)
  } else {
    sourceMode = 'geojson'
    map.addSource(SOURCE_ID, { type: 'geojson', data, promoteId: 'id' })
    map.addLayer({
      id: FILL_LAYER_ID,
      type: 'fill',
      source: SOURCE_ID,
      paint: {
        'fill-color': ['get', 'fillColor'],
        'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.95, 0.72],
      },
    })
    map.addLayer({
      id: LINE_LAYER_ID,
      type: 'line',
      source: SOURCE_ID,
      paint: {
        'line-color': '#ffffff',
        'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 1, 0.28],
        'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 2, 1],
      },
    })
    map.addLayer({
      id: LABEL_LAYER_ID,
      type: 'symbol',
      source: SOURCE_ID,
      minzoom: 13,
      layout: {
        'text-field': [
          'case',
          ['!=', ['get', 'name'], ''],
          ['get', 'name'],
          ['concat', ['get', 'id'], '斜坡'],
        ],
        'text-size': 14,
        'text-anchor': 'center',
      },
      paint: { 'text-color': '#ffffff', 'text-halo-color': '#383C41', 'text-halo-width': 1 },
    })
    map.on('mousemove', FILL_LAYER_ID, updateHover)
    map.on('mouseleave', FILL_LAYER_ID, clearHover)
  }
  if (data.features.length) {
    const bounds = bbox(data)
    map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 36, duration: 0, maxZoom: 13 })
  }
}

const exportImage = async (prepare) => {
  if (!map) return ''
  // 等待地图所有可见瓦片加载；否则右侧缩略图可能截到尚未完成的影像底图。
  const tilesReady = () => map?.areTilesLoaded()
    && (!map.getSource(SOURCE_ID) || map.isSourceLoaded(SOURCE_ID))
  const ready = await new Promise((resolve) => {
    let settled = false
    let timeout = null
    let rendered = false
    const finish = (isReady) => {
      if (settled) return
      settled = true
      window.clearTimeout(timeout)
      map?.off('idle', onIdle)
      map?.off('render', onRender)
      map?.off('sourcedata', onSourceData)
      map?.off('remove', onRemove)
      resolve(isReady)
    }

    const onSourceData = (event) => {
      if (event?.sourceId === SOURCE_ID && event?.isSourceLoaded) {
        map?.triggerRepaint()
      }
    }

    const onRender = () => { rendered = true }
    const onIdle = () => {
      if (rendered && tilesReady()) finish(true)
    }
    const onRemove = () => finish(false)

    timeout = window.setTimeout(() => finish(false), 15000)
    map.on('idle', onIdle)
    map.on('render', onRender)
    map.on('sourcedata', onSourceData)
    map.on('remove', onRemove)
    prepare?.()
    map.triggerRepaint()
  })
  if (!ready || !map) return ''
  return map.getCanvas().toDataURL('image/png')
}

const renderAndExport = async (config, units = props.units) => {
  return exportImage(() => {
    map?.resize()
    drawUnits(config, units)
  })
}

const showUnit = (unit) => {
  if (!map || !unit) return
  const feature = toFeatureCollection([unit]).features[0]
  if (!feature) return
  const center = centerOfMass(feature).geometry.coordinates
  popup.setLngLat(center).setDOMContent(createPopupContent(feature.properties)).addTo(map)
  map.flyTo({ center, zoom: Math.max(map.getZoom(), 13), duration: 800 })
}

const scheduleResize = () => {
  if (resizeFrame) return
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    map?.resize()
  })
}

onMounted(() => {
  map = new maplibregl.Map({
    container: mapContainerRef.value,
    center: [111.16, 30.75],
    zoom: 9.5,
    minZoom: 7,
    interactive: props.interactive,
    attributionControl: props.attributionControl,
    canvasContextAttributes: { preserveDrawingBuffer: props.preserveDrawingBuffer, antialias: false },
    style: {
      version: 8,
      sources: {
        'tdt-imagery': {
          type: 'raster',
          // 浏览器直连天地图官方服务（支持 HTTPS 与 CORS 跨域），多节点并发轮询加速，避免内网 Nginx 502
          tiles: [
            `https://t0.tianditu.gov.cn/img_w/wmts?service=wmts&request=GetTile&version=1.0.0&LAYER=img&tileMatrixSet=w&TileMatrix={z}&TileRow={y}&TileCol={x}&style=default&format=tiles&tk=${TDT_TOKEN}`,
            `https://t1.tianditu.gov.cn/img_w/wmts?service=wmts&request=GetTile&version=1.0.0&LAYER=img&tileMatrixSet=w&TileMatrix={z}&TileRow={y}&TileCol={x}&style=default&format=tiles&tk=${TDT_TOKEN}`,
            `https://t2.tianditu.gov.cn/img_w/wmts?service=wmts&request=GetTile&version=1.0.0&LAYER=img&tileMatrixSet=w&TileMatrix={z}&TileRow={y}&TileCol={x}&style=default&format=tiles&tk=${TDT_TOKEN}`,
            `https://t3.tianditu.gov.cn/img_w/wmts?service=wmts&request=GetTile&version=1.0.0&LAYER=img&tileMatrixSet=w&TileMatrix={z}&TileRow={y}&TileCol={x}&style=default&format=tiles&tk=${TDT_TOKEN}`,
          ],
          tileSize: 256,
          maxzoom: 18,
        },
      },
      layers: [
        { id: 'background', type: 'background', paint: { 'background-color': '#617185' } },
        { id: 'tdt-imagery', type: 'raster', source: 'tdt-imagery', paint: { 'raster-opacity': 1 } },
      ],
    },
  })
  resizeObserver = new ResizeObserver(scheduleResize)
  resizeObserver.observe(mapContainerRef.value)
  popup = new maplibregl.Popup({ className: 'dynamic-risk-popup', closeButton: false, closeOnClick: false, maxWidth: 'none' })
  map.on('load', () => {
    drawUnits()
    map.fitBounds([[110.2, 29.9], [112.15, 31.62]], { padding: 0, duration: 0, maxZoom: 8 })
    scheduleResize()
    emit('ready', map)
  })
})

watch(
  () => [props.units, props.levelField, props.levelColors, props.activeLevels, props.vectorTileUrl, props.vectorSourceLayer, props.chongqingSlopeStyle],
  () => drawUnits(),
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (resizeFrame) cancelAnimationFrame(resizeFrame)
  popup?.remove()
  if (map?.getLayer(FILL_LAYER_ID)) {
    map.off('mousemove', FILL_LAYER_ID, updateHover)
    map.off('mouseleave', FILL_LAYER_ID, clearHover)
  }
  map?.off('idle', updateUnitLabels)
  clearUnitLabels()
  map?.remove()
  popup = null
  map = null
})

defineExpose({ exportImage, renderAndExport, showUnit, resize: () => map?.resize() })
</script>

<style lang="less" scoped>
.dynamic-risk-map { position: relative; width: 100%; height: 100%; }
:deep(.maplibregl-ctrl-bottom-left), :deep(.maplibregl-ctrl-bottom-right) { display: none; }
</style>

<style lang="less">
.dynamic-risk-popup .maplibregl-popup-content { min-width: 276px; padding: 14px; border: 1px solid #ffffff; border-radius: 6px; background: rgba(241, 243, 252, 0.9); backdrop-filter: blur(4px); }
.dynamic-risk-popup .maplibregl-popup-tip { border-top-color: rgba(241, 243, 252, 0.9); }
.slope-unit-id-label { display: block; padding: 2px 4px; border: 1px solid rgba(255, 255, 255, 0.9); border-radius: 3px; background: rgba(28, 44, 66, 0.76); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35); color: #ffffff; font: 600 10px/1.2 Arial, sans-serif; white-space: nowrap; pointer-events: none; }
.risk-popup { color: #617185; font-size: 12px; }
.risk-popup-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.7); }
.risk-popup-header strong { color: #222527; font-size: 14px; font-weight: 500; }
.risk-popup-header span { flex: 0 0 auto; padding: 4px 6px; border-radius: 4px; color: #ffffff; }
.risk-popup-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 24px; }
.risk-popup-row strong { color: #383C41; font-weight: 500; text-align: right; }
</style>
