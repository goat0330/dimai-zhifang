// 仅供视觉预览与交互演示：不代表真实宜昌事件、预警或业务任务。
export const demoEventId = 'YC-DEMO-20261017-001'
export const demoMetrics = { reachCount: 0, totalCount: 0, taskCompleteCount: 0, taskTotalCount: 8, completeRate: 0 }
export const demoTasks = [
  { id: 101, type: 'retreat', taskName: '人员安置', responsiblePerson: '谭某艺', status: 'draft', inspectionSuggestion: '1. 核对受威胁人员及临时避险需求，将人员转移至选定的安全避险场所。\n2. 现场登记并确认安全路线、安置点与特殊人群。\n3. 通知网格责任人及值班人员，保持联系。' },
  { id: 102, type: 'inspect', taskName: '监测巡查（群测群防）', responsiblePerson: '吴某洋', status: 'draft', inspectionSuggestion: '1. 对疑似变形区域开展定点巡查，重点观察裂缝、崩塌迹象及坡脚变化。\n2. 核对降雨、位移和近期巡查记录，并持续形成文字、图片回传。\n3. 出现明显异常时及时上报。' },
  { id: 103, type: 'alarm', taskName: '警示防护', responsiblePerson: '谭某艺', status: 'draft', inspectionSuggestion: '1. 在临近坡体的道路和出入口设置警戒标识及必要隔离设施。\n2. 明确警示范围与引导路线，及时反馈现场完成情况。' },
  { id: 104, type: 'risk', taskName: '排危除险', responsiblePerson: '向方', status: 'draft', inspectionSuggestion: '1. 组织专业人员现场评估潜在危险，核查斜坡变形和外部诱发条件。\n2. 根据专业意见提出临时防护、排险或工程治理建议，须经审核后实施。' },
  { id: 105, type: 'govern', taskName: '治理工程', responsiblePerson: '待指定', status: 'pending', inspectionSuggestion: '按专业评估结果开展治理工程必要性核查，形成方案建议和资源需求。' },
  { id: 106, type: 'promotion', taskName: '宣传告知', responsiblePerson: '待指定', status: 'pending', inspectionSuggestion: '对涉险人员开展防灾告知和避险知识宣传，记录通知方式与覆盖范围。' },
  { id: 107, type: 'traffic', taskName: '交通管控', responsiblePerson: '待指定', status: 'pending', inspectionSuggestion: '核实临近道路通行情况，必要时提出临时限行建议并报授权部门批准。' },
  { id: 108, type: 'other', taskName: '后续跟踪', responsiblePerson: '待指定', status: 'pending', inspectionSuggestion: '复核执行反馈、后续监测要求和交接事项，并形成事件归档材料。' },
]
