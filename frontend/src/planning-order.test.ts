import { describe, expect, it } from 'vitest'

import { movePlanningProject, orderPlanningProjects } from './planning-order'
import type { DayPlanProject } from './types'

function project(id: string, name: string, owner: string | null, options: { waiting?: number; warnings?: number; open?: boolean; hasRun?: boolean } = {}): DayPlanProject {
  const hasRun = options.hasRun !== false
  return {
    id, code: id, name, owner_name: owner,
    run: hasRun ? { id: `run-${id}`, status: options.open === false ? 'APPROVED' : 'DRAFT', version: 1, revision: 1, open: options.open !== false, assigned_hours: 0, assignments: 0, warnings: options.warnings || 0, unseen_warnings: options.warnings || 0 } : null,
    people: [], free: [], off: [], off_plan: [],
    waiting: Array.from({ length: options.waiting || 0 }, (_, index) => ({ id: `${id}-${index}`, title: 'Việc', summary: null, source_type: 'ISSUE', issue: null, issue_url: null, intake_id: null, intake_public_id: null, priority: null, member_name: null, origin_at: null })),
  }
}

describe('Planning project order', () => {
  it('puts unowned CTO projects first, then projects needing attention', () => {
    const rows = [
      project('stable', 'Ổn định', 'Owner', { open: false }),
      project('warning', 'Có cảnh báo', 'Owner', { warnings: 1 }),
      project('unowned', 'Chưa có owner', null, { open: false }),
      project('waiting', 'Chờ việc', 'Owner', { waiting: 1 }),
    ]
    expect(orderPlanningProjects(rows, { mode: 'PRIORITY', project_ids: [] }, true).map((row) => row.id)).toEqual(['unowned', 'waiting', 'warning', 'stable'])
  })

  it('honors custom order and appends newly visible projects by priority', () => {
    const rows = [project('new', 'Mới', null), project('a', 'A', 'Owner'), project('b', 'B', 'Owner')]
    expect(orderPlanningProjects(rows, { mode: 'CUSTOM', project_ids: ['b', 'a'] }, true).map((row) => row.id)).toEqual(['b', 'a', 'new'])
    expect(movePlanningProject(['b', 'a', 'new'], 'new', 0)).toEqual(['new', 'b', 'a'])
  })
})
