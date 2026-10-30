import type { DayPlanProject } from './types'

export type PlanningProjectOrder = { mode: 'PRIORITY' | 'CUSTOM'; project_ids: string[] }

function comparePriority(left: DayPlanProject, right: DayPlanProject, isCto: boolean) {
  const leftKey = [
    isCto && !left.owner_name ? 0 : 1,
    left.waiting.length > 0 ? 0 : 1,
    (left.run?.unseen_warnings || 0) > 0 ? 0 : 1,
    !left.run || left.run.open ? 0 : 1,
  ]
  const rightKey = [
    isCto && !right.owner_name ? 0 : 1,
    right.waiting.length > 0 ? 0 : 1,
    (right.run?.unseen_warnings || 0) > 0 ? 0 : 1,
    !right.run || right.run.open ? 0 : 1,
  ]
  for (let index = 0; index < leftKey.length; index += 1) {
    if (leftKey[index] !== rightKey[index]) return leftKey[index] - rightKey[index]
  }
  return left.name.localeCompare(right.name, 'vi', { sensitivity: 'base' })
}

export function orderPlanningProjects(projects: DayPlanProject[], preference: PlanningProjectOrder, isCto: boolean) {
  const priority = [...projects].sort((left, right) => comparePriority(left, right, isCto))
  if (preference.mode !== 'CUSTOM') return priority
  const positions = new Map(preference.project_ids.map((id, index) => [id, index]))
  const ranked = priority.filter((project) => positions.has(project.id)).sort((left, right) => positions.get(left.id)! - positions.get(right.id)!)
  const unranked = priority.filter((project) => !positions.has(project.id))
  return [...ranked, ...unranked]
}

export function movePlanningProject(projectIds: string[], projectId: string, targetIndex: number) {
  const from = projectIds.indexOf(projectId)
  if (from < 0 || targetIndex < 0 || targetIndex >= projectIds.length || from === targetIndex) return projectIds
  const next = [...projectIds]
  next.splice(from, 1)
  next.splice(targetIndex, 0, projectId)
  return next
}
