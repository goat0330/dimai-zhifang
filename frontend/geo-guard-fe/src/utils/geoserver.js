/**
 * GeoServer WMS 图层服务配置
 * 旧业务图层仅按宜昌市编码/名称筛选；宜昌授权业务数据尚未接入。
 * 基础前缀：http://127.0.0.1:8080/geoserver（开发环境由 vite 代理 /geoserver，生产环境由 nginx 反向代理）
 */

// GeoServer 服务请求基础前缀
export const GEOSERVER_BASE_URL =
  import.meta.env.VITE_APP_GEOSERVER_PREFIX || '/geoserver'

// 1. 承灾体（房屋/承灾对象图层）配置
export const DISASTER_BODY_LAYER_CONFIG = {
  url: `${GEOSERVER_BASE_URL}/pku_user/wms`,
  layers: 'pku_user:data_house',
  parameters: {
    service: 'WMS',
    version: '1.1.0',
    request: 'GetMap',
    format: 'image/png',
    transparent: true,
    cql_filter: "city_code = '420500'",
    srs: 'EPSG:4326',
  },
}

// 2. 灾害体（隐患点/灾害点图层）配置
export const RISK_HAZARD_LAYER_CONFIG = {
  url: `${GEOSERVER_BASE_URL}/pku_user/wms`,
  layers: 'pku_user:v_hazard_point',
  parameters: {
    service: 'WMS',
    version: '1.1.1',
    request: 'GetMap',
    format: 'image/png',
    transparent: true,
    cql_filter: "city = '宜昌市'",
    srs: 'EPSG:4326',
  },
}

// 3. 风险区配置（对应图层控制中的风险区）
// 对应 GeoServer pku_user:data_risk_zone
export const RISK_AREA_LAYER_CONFIG = {
  url: `${GEOSERVER_BASE_URL}/pku_user/wms`,
  layers: 'pku_user:data_risk_zone',
  parameters: {
    service: 'WMS',
    version: '1.1.1',
    request: 'GetMap',
    styles: '',
    format: 'image/png',
    transparent: true,
    cql_filter: "city_code = '420500'",
    srs: 'EPSG:4326',
  },
}
