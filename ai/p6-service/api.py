"""Read-only unified P6 query API. Reads the packaged snapshot; no model execution."""
from contextlib import asynccontextmanager
from enum import Enum
import json
import os
import re
from pathlib import Path
from typing import Literal

import polars as pl
from fastapi import FastAPI, HTTPException, Path as ApiPath, Query
from pydantic import BaseModel, ConfigDict, Field
from dynamic_rainfall.routes import router as dynamic_router

HERE = Path(__file__).resolve().parent
PROFILE_PATH = Path(os.environ.get("P6_RUNTIME_PROFILE", HERE / "P6_runtime_profile.json"))
if not PROFILE_PATH.is_file():
    raise RuntimeError(f"Active P6 runtime profile is required: {PROFILE_PATH}")
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
DATA = Path(PROFILE.get("unified_data_path", HERE / "P6_SHEVR统一数据.parquet"))
DATASET_INFO_PATH = Path(PROFILE.get("dataset_info_path", HERE / "dataset_info.json"))
EXPECTED_UNITS = int(PROFILE["expected_units"])
ID_PATTERN = PROFILE["id_pattern"]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Asset(str, Enum):
    population = 'population'
    highway = 'highway'
    national_provincial = 'national_provincial'
    county_township = 'county_township'
    village_other = 'village_other'


SOURCE_ASSETS = {a.value: ('ambient_population' if a==Asset.population else a.value) for a in Asset}


class SValue(Model):
    score: float | None = Field(default=None, ge=0, le=1, description='P5连续评分有效像元的单元均值；无有效像元时为空')
    grade: Literal['S1','S2','S3','S4','S5'] | None = Field(default=None, description='按单元均值套用P5 Jenks断点')


class HValue(Model):
    score: float | None = Field(default=None, ge=0, le=1)
    grade: Literal['H1','H2','H3','H4','H5'] | None = None


class EValue(Model):
    score: float | None = Field(default=None, ge=0, le=1)
    grade: Literal['E1','E2','E3','E4','E5'] | None = None


class VValue(Model):
    score: float = Field(ge=1, le=5, description='AI条件情景的类别推荐分，允许小数')
    coefficient: float = Field(ge=.2, le=1, description='score/5的序数转换；不是损失率')


class RValue(Model):
    score: float | None = Field(default=None, ge=1, le=5, description='序数筛查分；零暴露资产的1分为筛查底线')
    grade: Literal['R1','R2','R3','R4','R5'] | None = None


class AssetE(Model):
    population: EValue
    highway: EValue
    national_provincial: EValue
    county_township: EValue
    village_other: EValue


class AssetV(Model):
    population: VValue
    highway: VValue
    national_provincial: VValue
    county_township: VValue
    village_other: VValue


class AssetR(Model):
    population: RValue
    highway: RValue
    national_provincial: RValue
    county_township: RValue
    village_other: RValue


class Exposure(Model):
    population_est: float = Field(ge=0, description='LandScan环境人口估计，单位人')
    road_length_m: float = Field(ge=0)
    highway_m: float = Field(ge=0)
    national_provincial_m: float = Field(ge=0)
    county_township_m: float = Field(ge=0)
    village_other_m: float = Field(ge=0)


class ExposureScores(Model):
    total: EValue
    hotspot: EValue
    population: EValue
    road: EValue
    by_asset: AssetE


class RiskScores(Model):
    overall: RValue
    by_asset: AssetR


class Unit(Model):
    slope_unit_id: str = Field(pattern=ID_PATTERN)
    county: str
    S: SValue
    H: HValue
    E: ExposureScores
    V: AssetV
    R: RiskScores
    exposure: Exposure


class UnitPage(Model):
    total: int
    offset: int
    limit: int
    items: list[Unit]


class BatchInput(Model):
    slope_unit_ids: list[str] = Field(min_length=1,max_length=500)


class BatchResult(Model):
    items: list[Unit]
    not_found: list[str]


class Lookup(Model):
    slope_unit_id: str
    county: str
    asset_type: Asset
    S: SValue
    H: HValue
    E: EValue
    V: VValue
    R: RValue
    overall_R: RValue


class County(Model):
    county: str
    total_units: int
    R1: int
    R2: int
    R3: int
    R4: int
    R5: int


class Store:
    def __init__(self,path=DATA):
        self.path=Path(path)
        self.frame=None
        self.index={}

    def load(self):
        frame=pl.read_parquet(self.path).sort('slope_unit_id')
        if frame.height!=EXPECTED_UNITS or frame['slope_unit_id'].n_unique()!=frame.height:
            raise ValueError(f'Unified snapshot must have {EXPECTED_UNITS} unique units')
        if frame['slope_unit_id'].null_count() or frame['county'].null_count():
            raise ValueError('Unified snapshot IDs and county assignments must be complete')
        if any(re.fullmatch(ID_PATTERN, str(key)) is None for key in frame['slope_unit_id']):
            raise ValueError('Unified snapshot contains IDs outside the active unit namespace')
        self.frame=frame
        self.index={key:i for i,key in enumerate(frame['slope_unit_id'])}

    def record(self,row):
        def band(score,grade):
            return {'score':row[score],'grade':row[grade]}
        e,v,r={},{},{}
        for asset,source in SOURCE_ASSETS.items():
            e[asset]=band('e_'+source+'_score','e_'+source+'_grade')
            v[asset]={'score':row['v_'+source+'_score'],'coefficient':row['v_'+source+'_coefficient']}
            r[asset]=band('r_'+source+'_score','r_'+source+'_grade')
        exposure={'population_est':row['population_est'],'road_length_m':row['road_length_m']}
        exposure.update({a+'_m':row['road_length_'+a+'_m'] for a in SOURCE_ASSETS if a!='population'})
        return {'slope_unit_id':row['slope_unit_id'],'county':row['county'],
                'S':band('s_score','s_grade'),'H':band('h_score','h_grade'),
                'E':{'total':band('E_total','e_grade'),'hotspot':band('E_hotspot','e_hotspot_grade'),
                     'population':band('e_population_score','e_population_grade'),
                     'road':band('e_road_score','e_road_grade'),'by_asset':e},
                'V':v,'R':{'overall':band('r_score','r_grade'),'by_asset':r},'exposure':exposure}

    def unit(self,key):
        i=self.index.get(key)
        return self.record(self.frame.row(i,named=True)) if i is not None else None

    def query(self,county,r_grade,asset,offset,limit):
        frame=self.frame
        if county is not None:
            frame=frame.filter(pl.col('county')==county)
        if r_grade is not None:
            field='r_grade' if asset is None else 'r_'+SOURCE_ASSETS[asset.value]+'_grade'
            frame=frame.filter(pl.col(field)==r_grade)
        return {'total':frame.height,'offset':offset,'limit':limit,
                'items':[self.record(row) for row in frame.slice(offset,limit).to_dicts()]}

    def counties(self):
        return self.frame.group_by('county').agg(
            pl.len().alias('total_units'),
            *[(pl.col('r_grade')==f'R{i}').sum().alias(f'R{i}') for i in range(1,6)]
        ).sort('county').to_dicts()


def create_app(store=None):
    store=store or Store()
    @asynccontextmanager
    async def lifespan(app):
        store.load()
        yield
    app=FastAPI(title='地脉智控宜昌风险数据服务',version='1.0.0',lifespan=lifespan,
                description='提供宜昌斜坡单元风险等级和动态风险查询接口。',
                docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store
    app.include_router(dynamic_router)

    @app.get('/health',operation_id='p6Health')
    def health():
        return {'status':'ok','rows':store.frame.height,'dataset':'宜昌风险数据'}

    @app.get('/schema.json',operation_id='p6UnitSchema')
    def schema():
        value = Unit.model_json_schema()
        value['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
        value['$id'] = 'urn:yichang:p6:shevr:unit:1.0'
        return value

    @app.get('/api/v1/info',operation_id='p6DatasetInfo')
    def info(slope_unit_id:str|None=Query(None,pattern=ID_PATTERN)):
        value=json.loads(DATASET_INFO_PATH.read_text(encoding='utf-8'))
        if slope_unit_id is not None:
            if slope_unit_id not in store.index:
                raise HTTPException(404,'Slope unit not found')
            value['slope_unit_id']=slope_unit_id
        return value

    @app.get('/api/v1/units',response_model=UnitPage,operation_id='p6ListUnits')
    def list_units(county:str|None=None,r_grade:str|None=Query(None,pattern=r'^R[1-5]$'),
                   asset_type:Asset|None=None,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=250)):
        return store.query(county,r_grade,asset_type,offset,limit)

    @app.get('/api/v1/units/{slope_unit_id}',response_model=Unit,operation_id='p6GetUnit')
    def get_unit(slope_unit_id:str=ApiPath(pattern=ID_PATTERN)):
        result=store.unit(slope_unit_id)
        if result is None:
            raise HTTPException(404,'Slope unit not found')
        return result

    @app.post('/api/v1/units/batch',response_model=BatchResult,operation_id='p6BatchUnits',
              description='仅查询，不写入；按请求顺序返回，缺失ID列入not_found。')
    def batch_units(body:BatchInput):
        items,missing=[],[]
        for key in body.slope_unit_ids:
            value=store.unit(key)
            if value is None:
                missing.append(key)
            else:
                items.append(value)
        return {'items':items,'not_found':missing}

    @app.get('/api/v1/counties',response_model=list[County],operation_id='p6CountySummary')
    def counties():
        return store.counties()

    @app.get('/api/v1/agents/risk_lookup',response_model=Lookup,operation_id='p6RiskLookup')
    def risk_lookup(slope_unit_id:str=Query(pattern=ID_PATTERN),asset_type:Asset=Asset.population):
        value=store.unit(slope_unit_id)
        if value is None:
            raise HTTPException(404,'Slope unit not found')
        return {'slope_unit_id':slope_unit_id,'county':value['county'],'asset_type':asset_type,
                'S':value['S'],'H':value['H'],'E':value['E']['by_asset'][asset_type.value],
                'V':value['V'][asset_type.value],'R':value['R']['by_asset'][asset_type.value],
                'overall_R':value['R']['overall']}
    return app


app=create_app()
