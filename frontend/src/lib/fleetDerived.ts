import type { FieldModel, Job, SimulationState, Tractor } from '../types/api'

export function jobProgressPct(job: Job): number {
  if (job.estimated_work_units <= 0) return 0
  return Math.max(
    0,
    Math.min(100, (job.completed_work_units / job.estimated_work_units) * 100),
  )
}

export function fieldJobs(state: SimulationState, fieldId: string): Job[] {
  return state.jobs.filter((j) => j.field_id === fieldId)
}

export function fieldStatus(
  state: SimulationState,
  field: FieldModel,
): 'idle' | 'active' | 'done' | 'blocked' {
  const jobs = fieldJobs(state, field.id)
  if (jobs.length === 0) return 'idle'
  if (jobs.every((j) => j.status === 'completed')) return 'done'
  if (jobs.some((j) => j.status === 'in_progress' || j.status === 'assigned')) return 'active'
  if (jobs.some((j) => j.status === 'blocked')) return 'blocked'
  return 'idle'
}

export function tractorDisplayPosition(tractor: Tractor): { x: number; y: number } {
  const { path, path_index, travel_cell_progress, position } = tractor
  if (tractor.status !== 'traveling' || path.length < 2) {
    return { x: position.x, y: position.y }
  }
  const from = path[Math.min(path_index, path.length - 1)]
  const to = path[Math.min(path_index + 1, path.length - 1)]
  if (!from || !to) return { x: position.x, y: position.y }
  const t = Math.max(0, Math.min(1, travel_cell_progress))
  return {
    x: from.x + (to.x - from.x) * t,
    y: from.y + (to.y - from.y) * t,
  }
}

export function deadlineTone(job: Job, simTime: number): 'ok' | 'warn' | 'late' {
  const remaining = job.deadline_minute - simTime
  if (remaining < 0) return 'late'
  if (remaining < 30) return 'warn'
  return 'ok'
}

export function latestDecisionFor(
  decisions: Array<{ tractor_id: string; job_id: string }>,
  tractorId: string,
  jobId: string | null,
) {
  if (!jobId) return undefined
  return [...decisions].reverse().find((d) => d.tractor_id === tractorId && d.job_id === jobId)
}
