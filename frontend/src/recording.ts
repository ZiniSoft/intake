import { useSyncExternalStore } from 'react'
import { api, ApiError } from './api'
import { recordingStore, type PendingRecording } from './recording-store'
import type { Meeting, MeetingDetail } from './types'

// One recording at a time, held outside any component: the settings live in the right sidebar and the words appear
// in the middle of the page, and both read the same state.

export type RecordingSource = 'TAB_AND_MIC' | 'MIC' | 'FILE'
export type RecordingPhase = 'idle' | 'starting' | 'recording' | 'stopping' | 'done'
// MEETING: several people; separated by speaker and summarised afterwards.
// DICTATION: one person speaking a request to fill the Intake being written.
export type RecordingKind = 'MEETING' | 'DICTATION'
// `at` is the second of the recording at which the sentence began.
export type SpokenLine = { text: string; at: number }
// How the sound is getting to the server: chunks kept on this computer, chunks the server has confirmed, and
// whether the uploads are currently failing and being retried.
export type SyncState = { stored: number; uploaded: number; failing: boolean }
// Measured at the gateway every few seconds: audio it still owes the provider (its own line out), the widest
// gap between the frames this browser sent (the line in), and the provider's round trip.
export type StreamHealth = { backlogSeconds: number; clientGapMs: number; providerRttMs: number | null; dropped: number }

export type RecordingState = {
  phase: RecordingPhase
  kind: RecordingKind
  source: RecordingSource
  lines: SpokenLine[]
  partial: string
  partialAt: number | null
  elapsed: number
  startedAt: number | null
  notice?: string
  error?: unknown
  meetingId?: string
  // Which part of the meeting is being recorded; 1 until the time limit rolls it over.
  partNumber?: number
  rewriting: boolean
  rewritten?: string
  rewrittenFor?: string
  sync: SyncState | null
  // Seconds of live-transcript audio waiting in the socket because the line cannot carry it: 0 on a good line.
  streamLag: number
  streamHealth: StreamHealth | null
}

// Every field is listed, the optional ones as undefined: a reset is written over the current state, so a field left
// out here would survive it. That is how the AI rewrite of one recording once reached the next.
const initial: RecordingState = {
  phase: 'idle', kind: 'MEETING', source: 'MIC', lines: [], partial: '', partialAt: null, elapsed: 0, startedAt: null, rewriting: false,
  notice: undefined, error: undefined, meetingId: undefined, partNumber: undefined, rewritten: undefined, rewrittenFor: undefined, sync: null, streamLag: 0, streamHealth: null,
}

let state = initial
let stop: (() => Promise<void>) | null = null
const listeners = new Set<() => void>()

function set(patch: Partial<RecordingState>) {
  state = { ...state, ...patch }
  listeners.forEach((listener) => listener())
}

export function useRecording(): RecordingState {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => state)
}

export function recordingActive() {
  return state.phase === 'starting' || state.phase === 'recording' || state.phase === 'stopping'
}

export async function stopRecording() {
  await stop?.()
}

export function resetRecording() {
  if (recordingActive()) return
  set({ ...initial })
}

// Leaving a page that records: end the recording, then forget it. The state lives outside the pages, so without
// this the next page that shows a recording would show the previous one, ready to be put into a new request.
export async function leaveRecording() {
  // A meeting runs for an hour while people look things up elsewhere in the app: it keeps recording, and the top
  // bar shows it. Only a spoken request, which belongs to the page it fills, ends when that page is left.
  if (state.kind === 'MEETING' && recordingActive()) return
  await stop?.()
  set({ ...initial })
}

// Closing or reloading the tab ends a recording for real: the browser asks first while one is running.
window.addEventListener('beforeunload', (event) => {
  if (!recordingActive()) return
  event.preventDefault()
  event.returnValue = ''
})

const PCM_BYTES_PER_SECOND = 16000 * 2
const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

// ---- Uploading from the local store ------------------------------------------------------------------------

// Sends the chunks of one meeting to the server in order, from IndexedDB, and keeps trying until none is left.
// A chunk is deleted locally only after the server confirmed it. The server takes chunks strictly in sequence
// and knows how many it holds, so after any failure the two sides agree again by asking it.
class Uploader {
  stored = 0
  uploaded = 0
  failing = false
  private running = false
  private attempts = 0
  private waiters: (() => void)[] = []

  constructor(private meetingId: string, private onChange: (sync: SyncState) => void) {}

  private notify() { this.onChange({ stored: this.stored, uploaded: this.uploaded, failing: this.failing }) }

  async push(sequence: number, blob: Blob) {
    await recordingStore.putChunk({ meetingId: this.meetingId, sequence, blob, createdAt: Date.now() })
    this.stored = Math.max(this.stored, sequence + 1)
    this.notify()
    void this.pump()
  }

  // Resolves once no chunk of this meeting remains on this computer.
  drained(): Promise<void> {
    return new Promise((resolve) => { this.waiters.push(resolve); void this.pump() })
  }

  async pump() {
    if (this.running) return
    this.running = true
    try {
      for (;;) {
        const chunks = await recordingStore.chunksOf(this.meetingId)
        if (chunks.length === 0) break
        this.stored = Math.max(this.stored, chunks[chunks.length - 1].sequence + 1)
        const chunk = chunks[0]
        try {
          const body = new FormData()
          body.append('file', chunk.blob, `chunk-${chunk.sequence}.webm`)
          const meeting = await api<Meeting>(`/meetings/${this.meetingId}/audio?sequence=${chunk.sequence}`, { method: 'POST', body })
          await recordingStore.deleteChunk(this.meetingId, chunk.sequence)
          this.uploaded = meeting.audio_chunk_count
          this.attempts = 0
          this.failing = false
        } catch (error) {
          if (error instanceof ApiError && error.code === 'AUDIO_CHUNK_OUT_OF_ORDER') {
            // The server is ahead (a reply was lost after it stored the chunk): drop what it already holds.
            const meeting = await api<Meeting>(`/meetings/${this.meetingId}`)
            this.uploaded = meeting.audio_chunk_count
            for (const held of chunks) if (held.sequence < meeting.audio_chunk_count) await recordingStore.deleteChunk(this.meetingId, held.sequence)
            if (chunk.sequence >= meeting.audio_chunk_count) throw error
          } else if (error instanceof ApiError && (error.code === 'MEETING_NOT_RECORDING' || error.status === 404)) {
            // The meeting was finished or deleted elsewhere: the sound kept here has nowhere to go.
            await recordingStore.forget(this.meetingId)
            break
          } else {
            this.attempts += 1
            this.failing = this.attempts >= 2
            this.notify()
            await delay(Math.min(30_000, 1000 * 2 ** Math.min(this.attempts, 5)))
            continue
          }
        }
        this.notify()
      }
    } finally {
      this.running = false
    }
    this.notify()
    this.waiters.splice(0).forEach((resolve) => resolve())
  }
}

// Ends the meeting on the server once every chunk is there, with the length measured while recording.
async function completeMeeting(meetingId: string, elapsed: number): Promise<MeetingDetail> {
  const finished = await api<MeetingDetail>(`/meetings/${meetingId}/finish`, { method: 'POST', body: JSON.stringify({ duration_seconds: elapsed }) })
  await recordingStore.forget(meetingId)
  return finished
}

// ---- Recordings this browser still owes the server ------------------------------------------------------------

export type PendingSync = { meetings: number; chunks: number; failing: boolean; finished?: string }
let pending: PendingSync = { meetings: 0, chunks: 0, failing: false }
const pendingListeners = new Set<() => void>()
function setPending(patch: Partial<PendingSync>) {
  pending = { ...pending, ...patch }
  pendingListeners.forEach((listener) => listener())
}
export function usePendingSync(): PendingSync {
  return useSyncExternalStore((listener) => { pendingListeners.add(listener); return () => { pendingListeners.delete(listener) } }, () => pending)
}

let resuming = false
// Called when the app opens: a meeting whose tab was closed while recording, or while its sound was still going
// up, is sent on from here and ended. The live transcript of it is already on the server.
export async function resumePendingRecordings() {
  if (resuming || !recordingStore.available()) return
  resuming = true
  try {
    const records = (await recordingStore.pending()).filter((record) => record.meetingId !== state.meetingId || !recordingActive())
    let chunks = 0
    for (const record of records) chunks += (await recordingStore.chunksOf(record.meetingId)).length
    setPending({ meetings: records.length, chunks, failing: false })
    for (const record of records) {
      try {
        const meeting = await api<Meeting>(`/meetings/${record.meetingId}`)
        if (meeting.status !== 'RECORDING') { await recordingStore.forget(record.meetingId); continue }
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) { await recordingStore.forget(record.meetingId); continue }
        throw error
      }
      const uploader = new Uploader(record.meetingId, (sync) => setPending({ failing: sync.failing, chunks: Math.max(sync.stored - sync.uploaded, 0) }))
      await uploader.drained()
      await completeMeeting(record.meetingId, record.elapsed)
      setPending({ meetings: Math.max(pending.meetings - 1, 0), finished: record.meetingId })
    }
  } catch {
    setPending({ failing: true })
  } finally {
    resuming = false
    setPending({ chunks: 0, meetings: 0 })
  }
}

export function dismissPendingSync() { setPending({ finished: undefined }) }

// ---- Recording ---------------------------------------------------------------------------------------------------

export async function startRecording({ source, projectCode, kind }: { source: Exclude<RecordingSource, 'FILE'>; projectCode: string; kind: RecordingKind }) {
  if (recordingActive()) return
  set({ ...initial, phase: 'starting', kind, source })
  const streams: MediaStream[] = []
  const release = () => streams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()))
  try {
    streams.push(await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }))
    if (source === 'TAB_AND_MIC') {
      // Only the sound of the tab is wanted; the picture is asked for as small and slow as the browser allows,
      // since capturing it at full size costs the machine more than the recording itself.
      const display = await navigator.mediaDevices.getDisplayMedia({ video: { width: { max: 320 }, height: { max: 180 }, frameRate: { max: 2 } }, audio: true })
      streams.push(display)
      if (display.getAudioTracks().length === 0) throw new Error('Tab hoặc màn hình bạn chọn không chia sẻ âm thanh. Hãy chọn lại và tích "Chia sẻ âm thanh".')
    }
    const meeting = await api<Meeting>('/meetings', { method: 'POST', body: JSON.stringify({ project_id: projectCode || null, source, kind }) })
    set({ meetingId: meeting.id, partNumber: meeting.part_number || 1 })
    const context = new AudioContext({ sampleRate: 16000 })
    await context.audioWorklet.addModule('/pcm-worklet.js')
    const mix = context.createGain()
    streams.forEach((stream) => context.createMediaStreamSource(new MediaStream(stream.getAudioTracks())).connect(mix))
    const capture = new AudioWorkletNode(context, 'pcm-capture')
    const recorded = context.createMediaStreamDestination()
    mix.connect(capture)
    mix.connect(recorded)
    // A hidden tab that makes no sound is slowed to a crawl by Chrome after five minutes. A silent path to the
    // speakers and a held Web Lock mark the page as busy, so the recording goes on while the user is in other tabs.
    const silent = context.createGain()
    silent.gain.value = 0
    mix.connect(silent)
    silent.connect(context.destination)
    let releaseLock: (() => void) | null = null
    if (navigator.locks) void navigator.locks.request('intake-recording', () => new Promise<void>((resolve) => { releaseLock = resolve })).catch(() => undefined)

    const startedAt = Date.now()
    const second = () => Math.floor((Date.now() - startedAt) / 1000)
    // The sound goes to this computer first, then to the server from there (see recording-store.ts).
    const local = recordingStore.available()

    // One part is one meeting on the server, with its own socket for the live words, its own recorder and its own
    // uploads. At the time limit the recording rolls over to the next part without touching the microphone.
    type Part = { meeting: Meeting; socket: WebSocket | null; closing: boolean; reconnects: number; recorder: MediaRecorder; uploader: Uploader | null; record: PendingRecording; direct: Promise<unknown>; startedAt: number; sequence: number; carried: SpokenLine[] }
    let stopped = false
    let rolling = false
    let current: Part

    // The live words travel on a socket that can drop (a sleeping laptop, a hidden tab, a proxy). The recorder does not
    // depend on it, so a dropped socket is reopened for as long as the part is the one being recorded.
    const connect = (part: Part): WebSocket => {
      const socket = new WebSocket(`${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/v1/meetings/${part.meeting.id}/stream`)
      socket.binaryType = 'arraybuffer'
      socket.onopen = () => { part.reconnects = 0 }
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data as string) as { type: string; text?: string; code?: string; backlog_seconds?: number; client_gap_ms?: number; provider_rtt_ms?: number | null; dropped?: number }
        if (message.type === 'partial') {
          // The first words of a sentence set its time; later corrections of the same sentence keep it.
          const text = message.text || ''
          set({ partial: text, partialAt: text ? state.partialAt ?? second() : null })
        } else if (message.type === 'committed') {
          const text = message.text?.trim()
          set({ lines: text ? [...state.lines, { text, at: state.partialAt ?? second() }] : state.lines, partial: '', partialAt: null })
        } else if (message.type === 'reconnecting') set({ notice: 'Mất kết nối tới dịch vụ chuyển chữ, đang nối lại. Bản ghi âm vẫn được lưu.' })
        else if (message.type === 'no_live_text') set({ notice: 'Nhà cung cấp giọng nói này không có chữ trực tiếp: chữ sẽ hiện sau khi bạn kết thúc cuộc họp. Bản ghi âm vẫn được lưu.' })
        else if (message.type === 'ready') set({ notice: undefined })
        else if (message.type === 'health') set({ streamHealth: { backlogSeconds: message.backlog_seconds || 0, clientGapMs: message.client_gap_ms || 0, providerRttMs: message.provider_rtt_ms ?? null, dropped: message.dropped || 0 } })
        else if (message.type === 'limit') void rollover()
        else if (message.type === 'error') set({ notice: 'Không chuyển chữ được lúc này. Bản ghi âm vẫn được lưu.' })
      }
      socket.onclose = (event) => {
        if (stopped || part.closing || current !== part || event.code === 4401 || event.code === 4404 || event.code === 4503) return
        // A normal close after the time limit is followed by the next part; anything else is a drop.
        part.reconnects += 1
        set({ notice: 'Kết nối chữ trực tiếp bị ngắt, đang nối lại. Bản ghi âm vẫn được lưu.' })
        window.setTimeout(() => { if (!stopped && !part.closing && current === part) part.socket = connect(part) }, Math.min(1000 * 2 ** Math.min(part.reconnects, 4), 15_000))
      }
      return socket
    }

    const openPart = async (part: Meeting, carried: SpokenLine[]): Promise<Part> => {
      const partStartedAt = Date.now()
      const record: PendingRecording = { meetingId: part.id, projectCode, startedAt: partStartedAt, elapsed: 0, stopped: false, nextSequence: 0 }
      if (local) await recordingStore.putMeeting(record)
      const uploader = local ? new Uploader(part.id, (sync) => set({ sync })) : null
      const recorder = new MediaRecorder(recorded.stream, { mimeType: 'audio/webm;codecs=opus' })
      const opened: Part = { meeting: part, socket: null, closing: false, reconnects: 0, recorder, uploader, record, direct: Promise.resolve(), startedAt: partStartedAt, sequence: 0, carried }
      opened.socket = connect(opened)
      recorder.ondataavailable = (event) => {
        if (event.data.size === 0) return
        const chunk = opened.sequence
        opened.sequence += 1
        if (uploader) {
          opened.record.nextSequence = opened.sequence
          opened.record.elapsed = Math.floor((Date.now() - partStartedAt) / 1000)
          void recordingStore.putMeeting({ ...opened.record }).then(() => uploader.push(chunk, event.data)).catch((error) => set({ error }))
        } else {
          // No IndexedDB (a private window, say): straight to the server, in order, as before.
          opened.direct = opened.direct.then(() => {
            const body = new FormData()
            body.append('file', event.data, `chunk-${chunk}.webm`)
            return api(`/meetings/${part.id}/audio?sequence=${chunk}`, { method: 'POST', body })
          }).catch((error) => set({ error }))
        }
      }
      recorder.start(10_000)
      return opened
    }

    // Stops a part's recorder and socket, sends what is left and finishes it on the server. The page is only told
    // about uploads that have to go on in the background when this is the last part.
    const closePart = async (part: Part, last: boolean): Promise<MeetingDetail | null> => {
      const recorderStopped = new Promise((resolve) => part.recorder.addEventListener('stop', resolve, { once: true }))
      if (part.recorder.state !== 'inactive') part.recorder.stop()
      await recorderStopped
      part.closing = true
      part.socket?.close()
      const elapsed = Math.floor((Date.now() - part.startedAt) / 1000)
      // The gateway commits the last words after the stream closes; give it a moment before reading them back.
      const gatewaySettled = delay(3500)
      if (part.uploader) {
        const uploader = part.uploader
        await recordingStore.putMeeting({ ...part.record, elapsed, stopped: true })
        // Wait for the uploads a while; a line that is down for longer hands the rest to the background.
        const drained = await Promise.race([uploader.drained().then(() => true), delay(20_000).then(() => false)])
        await gatewaySettled
        if (!drained) {
          if (last) {
            const left = Math.max(uploader.stored - uploader.uploaded, 0)
            set({ notice: `Còn ${left} đoạn ghi âm chưa lên server; sẽ tự gửi tiếp và hoàn tất khi đường truyền có lại. Đừng xóa dữ liệu trình duyệt trước đó.` })
          }
          void uploader.drained().then(() => completeMeeting(part.meeting.id, elapsed)).then((finished) => {
            if (last && state.meetingId === part.meeting.id) set({ notice: undefined, lines: [...part.carried, ...realtimeLines(finished, part.carried.length)] })
            setPending({ finished: part.meeting.id })
          }).catch((error) => { if (state.meetingId === part.meeting.id) set({ error }) })
          return null
        }
      } else {
        await part.direct
        await gatewaySettled
      }
      return completeMeeting(part.meeting.id, elapsed)
    }

    const rollover = async () => {
      if (rolling || stopped) return
      rolling = true
      try {
        const next = await api<Meeting>('/meetings', { method: 'POST', body: JSON.stringify({ source, kind, continues_meeting_id: current.meeting.id }) })
        const previous = current
        current = await openPart(next, state.lines)
        set({ meetingId: next.id, partNumber: next.part_number, notice: `Quá ${next.max_minutes} phút: tiếp tục ghi ở phần ${next.part_number}; phần trước đang được xử lý.` })
        void closePart(previous, false).catch((error) => set({ error }))
      } catch (error) {
        set({ error })
        void stop?.()
      } finally {
        rolling = false
      }
    }

    current = await openPart(meeting, [])
    capture.port.onmessage = (event) => { if (current.socket?.readyState === WebSocket.OPEN) current.socket.send(event.data as ArrayBuffer) }

    const timer = window.setInterval(() => {
      set({ elapsed: second(), streamLag: Math.round((current.socket?.bufferedAmount ?? 0) / PCM_BYTES_PER_SECOND) })
      if (Math.floor((Date.now() - current.startedAt) / 1000) >= meeting.max_minutes * 60) void rollover()
    }, 1000)
    streams.forEach((stream) => stream.getTracks().forEach((track) => {
      track.addEventListener('ended', () => {
        if (stopped) return
        set({ notice: 'Micro hoặc nguồn âm thanh đã bị ngắt (rút thiết bị, đổi thiết bị hoặc tắt chia sẻ). Bản ghi đến lúc này đã được lưu và đang hoàn tất.' })
        void stop?.()
      })
      track.addEventListener('mute', () => { if (!stopped) set({ notice: 'Micro đang bị tắt tiếng bởi trình duyệt hoặc hệ thống, nên chưa thu được âm thanh. Kiểm tra quyền micro và thiết bị đang chọn.' }) })
      track.addEventListener('unmute', () => { if (!stopped) set({ notice: undefined }) })
    }))
    // The audio engine can be suspended (sleep, another app taking the device); bring it back, or say so.
    const resumeAudio = () => {
      if (stopped || context.state === 'running') return
      void context.resume().catch(() => undefined).then(() => {
        if (!stopped && context.state !== 'running') set({ notice: 'Bộ thu âm bị tạm dừng bởi trình duyệt. Hãy quay lại tab Intake; bản ghi đến lúc này đã được lưu.' })
      })
    }
    context.addEventListener('statechange', resumeAudio)
    const onVisibility = () => {
      if (stopped) return
      if (document.visibilityState === 'visible') { resumeAudio(); return }
      set({ notice: 'Đang ghi âm khi tab ở nền. Bản ghi vẫn tiếp tục; nếu máy chuyển sang chế độ ngủ thì sẽ bị ngắt.' })
    }
    document.addEventListener('visibilitychange', onVisibility)

    stop = async () => {
      if (stopped) return
      stopped = true
      set({ phase: 'stopping' })
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      context.removeEventListener('statechange', resumeAudio)
      releaseLock?.()
      capture.disconnect()
      release()
      const part = current
      try {
        const finished = await closePart(part, true)
        await context.close()
        if (finished) set({ lines: [...part.carried, ...realtimeLines(finished, part.carried.length)] })
      } catch (error) {
        set({ error })
      }
      set({ partial: '', partialAt: null, phase: 'done' })
      stop = null
    }
    set({ phase: 'recording', startedAt })
  } catch (error) {
    release()
    set({
      phase: 'idle',
      error: error instanceof DOMException && error.name === 'NotAllowedError' ? new Error('Bạn chưa cấp quyền micro hoặc chia sẻ màn hình cho trang này.') : error,
    })
  }
}

// What the server kept is the record; the times were only measured here.
// The live lines of one part as the server kept them, timed from what the page saw; `offset` is how many lines of
// earlier parts come before them in the page.
function realtimeLines(finished: MeetingDetail, offset = 0): SpokenLine[] {
  const saved = finished.segments.filter((segment) => segment.source === 'REALTIME').map((segment) => segment.text || '').filter(Boolean)
  return saved.length > 0 ? saved.map((text, index) => ({ text, at: state.lines[offset + index]?.at ?? state.lines.at(-1)?.at ?? 0 })) : state.lines.slice(offset)
}

export async function uploadRecording(file: File, projectCode: string) {
  if (recordingActive()) return
  set({ ...initial, phase: 'starting', kind: 'MEETING', source: 'FILE' })
  try {
    const meeting = await api<Meeting>('/meetings', { method: 'POST', body: JSON.stringify({ project_id: projectCode || null, source: 'FILE', title: file.name.slice(0, 200) }) })
    set({ meetingId: meeting.id })
    const partSize = 4 * 1024 * 1024
    const parts = Math.max(Math.ceil(file.size / partSize), 1)
    for (let index = 0; index < parts; index += 1) {
      set({ notice: `Đang tải lên phần ${index + 1}/${parts}…` })
      const body = new FormData()
      body.append('file', file.slice(index * partSize, (index + 1) * partSize, file.type || 'audio/mpeg'), file.name)
      await api(`/meetings/${meeting.id}/audio?sequence=${index}`, { method: 'POST', body })
    }
    await api(`/meetings/${meeting.id}/finish`, { method: 'POST' })
    set({ notice: undefined, phase: 'done' })
  } catch (error) {
    set({ notice: undefined, phase: 'idle', error })
  }
}

// The spoken words rewritten as a short request. The AI worker does it; this asks, then waits for the answer.
export async function rewriteRecording(): Promise<string> {
  const id = state.meetingId
  // The answer is kept only for the recording it was written from.
  if (state.rewritten && state.rewrittenFor === id) return state.rewritten
  if (!id) throw new Error('Chưa có bản ghi nào để viết lại.')
  set({ rewriting: true })
  try {
    let detail = await api<MeetingDetail>(`/meetings/${id}/rewrite`, { method: 'POST' })
    for (let attempt = 0; attempt < 45 && detail.rewrite_status === 'PENDING'; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
      detail = await api<MeetingDetail>(`/meetings/${id}/rewrite`)
    }
    if (detail.rewrite_status === 'PENDING') throw new Error('AI chưa viết xong sau một phút. Hãy thử lại, hoặc dùng bản thô.')
    if (detail.rewrite_status !== 'DONE' || !detail.rewrite_text) throw new Error('AI không viết lại được lúc này. Hãy thử lại, hoặc dùng bản thô.')
    set({ rewritten: detail.rewrite_text, rewrittenFor: id })
    return detail.rewrite_text
  } finally {
    set({ rewriting: false })
  }
}
