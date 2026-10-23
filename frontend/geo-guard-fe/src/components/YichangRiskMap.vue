<template>
  <section class="map-frame">
    <div ref="mapHost" class="map-canvas" role="img" aria-label="宜昌斜坡单元风险地图"></div>
    <div class="map-tools">
      <button :class="{ active: showCounties }" @click="toggleCounties">县级边界</button>
      <button :class="{ active: showRoads }" @click="toggleRoads">道路</button>
      <button :class="{ active: showWater }" @click="toggleWater">水系</button>
    </div>
    <div class="map-caption">宜昌市 · 本地地图数据</div>
    <div v-if="mapError" class="map-error">{{ mapError }}</div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

const props = defineProps({
  riskField: { type: String, required: true },
  gradeFilter: { type: String, default: '' },
  countyFilter: { type: String, default: '' },
})

const mapHost = ref(null)
const mapError = ref('')
const showCounties = ref(true)
const showRoads = ref(false)
const showWater = ref(false)
let map
let popup

const colors = ['#dcefe5', '#a9d7b5', '#f5dc87', '#efaa66', '#dc6a5d']

function riskColorExpression() {
  return ['match', ['get', props.riskField],
    'R1', colors[0], 'R2', colors[1], 'R3', colors[2], 'R4', colors[3], 'R5', colors[4], '#b9c5cc']
}

function applyRiskFilter() {
  if (!map?.getLayer('risk-fill')) return
  const filters = [['has', props.riskField]]
  if (props.gradeFilter) filters.push(['==', ['get', props.riskField], props.gradeFilter])
  if (props.countyFilter) filters.push(['==', ['get', 'county'], props.countyFilter])
  map.setFilter('risk-fill', ['all', ...filters])
}

function setVisibility(layerId, visible) {
  if (map?.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none')
}

function addLocalSource(id, url) {
  if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data: url, promoteId: 'id' })
}

function addCountyLayer() {
  if (map.getLayer('county-lines')) return
  addLocalSource('county-data', '/geo/yichang/yichang_county_units_2023.geojson')
  map.addLayer({
    id: 'county-lines', type: 'line', source: 'county-data',
    paint: { 'line-color': '#536d80', 'line-width': 1.15, 'line-opacity': 0.76 },
  })
}

function toggleCounties() {
  showCounties.value = !showCounties.value
  if (showCounties.value) addCountyLayer()
  setVisibility('county-lines', showCounties.value)
}

function toggleRoads() {
  showRoads.value = !showRoads.value
  if (showRoads.value && !map.getLayer('road-lines')) {
    addLocalSource('road-data', '/geo/yichang/yichang_roads_2025.geojson')
    map.addLayer({
      id: 'road-lines', type: 'line', source: 'road-data',
      paint: { 'line-color': '#f4f0dc', 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.35, 12, 1.35], 'line-opacity': 0.8 },
    })
  }
  setVisibility('road-lines', showRoads.value)
}

function toggleWater() {
  showWater.value = !showWater.value
  if (showWater.value && !map.getLayer('water-fill')) {
    addLocalSource('water-polygons', '/geo/yichang/yichang_water_polygons_2025.geojson')
    addLocalSource('water-lines', '/geo/yichang/yichang_water_lines_2025.geojson')
    map.addLayer({ id: 'water-fill', type: 'fill', source: 'water-polygons', paint: { 'fill-color': '#a8d5e7', 'fill-opacity': 0.48 } })
    map.addLayer({ id: 'water-lines', type: 'line', source: 'water-lines', paint: { 'line-color': '#70b8d3', 'line-width': 1.1, 'line-opacity': 0.72 } })
  }
  setVisibility('water-fill', showWater.value)
  setVisibility('water-lines', showWater.value)
}

function showFeatureDetails(event) {
  const feature = map.queryRenderedFeatures(event.point, { layers: ['risk-fill'] })[0]
  if (!feature) return
  const props = feature.properties || {}
  const grade = props[props.riskField]
  const title = document.createElement('strong')
  title.textContent = props.slope_unit_id || '斜坡单元'
  const county = document.createElement('div')
  county.textContent = props.county || '宜昌市'
  const risk = document.createElement('div')
  risk.textContent = `风险等级：${grade || '暂无等级'}`
  const content = document.createElement('div')
  content.className = 'map-popup-content'
  content.append(title, county, risk)
  popup?.remove()
  popup = new maplibregl.Popup({ closeButton: true, maxWidth: '240px' }).setLngLat(event.lngLat).setDOMContent(content).addTo(map)
}

onMounted(() => {
  map = new maplibregl.Map({
    container: mapHost.value,
    style: {
      version: 8,
      sources: {},
      layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eaf0ee' } }],
    },
    center: [111.1, 30.7],
    zoom: 7.1,
    minZoom: 7,
    maxZoom: 15,
    attributionControl: true,
    pitchWithRotate: false,
    dragRotate: false,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.on('load', () => {
    addLocalSource('city-boundary', '/geo/yichang/yichang_city_boundary_2022.geojson')
    map.addSource('risk-units', {
      type: 'vector',
      tiles: [`${window.location.origin}/p6/api/v1/dynamic/tiles/{z}/{x}/{y}.pbf?scenario=dynamic&tile_revision=4`],
      minzoom: 7,
      maxzoom: 15,
      scheme: 'xyz',
      promoteId: { p6_dynamic_latest: 'slope_unit_id' },
    })
    map.addLayer({
      id: 'risk-fill', type: 'fill', source: 'risk-units', 'source-layer': 'p6_dynamic_latest',
      paint: { 'fill-color': riskColorExpression(), 'fill-opacity': 0.78, 'fill-outline-color': '#f8faf8' },
    })
    map.addLayer({
      id: 'city-outline', type: 'line', source: 'city-boundary',
      paint: { 'line-color': '#287c78', 'line-width': 2.2, 'line-opacity': 0.94 },
    })
    addCountyLayer()
    applyRiskFilter()
    map.once('idle', () => {
      console.info('[YichangRiskMap]', JSON.stringify({
        zoom: map.getZoom(),
        sourceLoaded: map.isSourceLoaded('risk-units'),
        sourceFeatures: map.querySourceFeatures('risk-units', { sourceLayer: 'p6_dynamic_latest' }).length,
        renderedFeatures: map.queryRenderedFeatures({ layers: ['risk-fill'] }).length,
      }))
    })
    map.on('click', 'risk-fill', showFeatureDetails)
    map.on('mouseenter', 'risk-fill', () => { map.getCanvas().style.cursor = 'pointer' })
    map.on('mouseleave', 'risk-fill', () => { map.getCanvas().style.cursor = '' })
    map.fitBounds([[110.24, 29.93], [112.1, 31.59]], { padding: 28, duration: 0 })
  })
  map.on('error', (event) => {
    const url = event?.error?.url || ''
    if (url.includes('/p6/')) mapError.value = '风险图层暂时不可用，请确认 P6 服务已启动。'
    if (url.includes('/geo/yichang/')) mapError.value = '本地宜昌地图数据读取失败。'
  })
})

watch(() => [props.riskField, props.gradeFilter, props.countyFilter], () => {
  if (!map) return
  if (map.getLayer('risk-fill')) map.setPaintProperty('risk-fill', 'fill-color', riskColorExpression())
  applyRiskFilter()
})

onBeforeUnmount(() => {
  popup?.remove()
  map?.remove()
})
</script>

<style scoped>
.map-frame { position: relative; width: 100%; height: 100%; min-height: 420px; overflow: hidden; background: #eaf0ee; }
.map-canvas { position: absolute; inset: 0; }
.map-tools { position: absolute; z-index: 2; top: 14px; left: 14px; display: flex; gap: 6px; padding: 5px; border: 1px solid #e2e9e8; border-radius: 10px; background: rgba(255,255,255,.94); box-shadow: 0 4px 16px rgba(32,58,69,.1); }
.map-tools button { padding: 7px 10px; color: #5d6d75; border-radius: 7px; cursor: pointer; font-size: 11px; }
.map-tools button.active { color: #196f67; background: #e8f4f1; font-weight: 650; }
.map-caption { position: absolute; z-index: 2; right: 12px; bottom: 12px; padding: 7px 10px; color: #61737b; border: 1px solid rgba(224,233,231,.8); border-radius: 7px; background: rgba(255,255,255,.88); font-size: 10px; }
.map-error { position: absolute; z-index: 3; left: 50%; top: 50%; max-width: 85%; padding: 12px 16px; transform: translate(-50%,-50%); color: #8f483e; border: 1px solid #edd0c8; border-radius: 9px; background: #fff7f4; font-size: 13px; box-shadow: 0 8px 26px rgba(0,0,0,.1); }
:deep(.maplibregl-popup-content) { padding: 12px 14px; color: #314654; line-height: 1.7; }
:deep(.map-popup-content strong) { display: block; color: #1d3d4e; }
</style>
