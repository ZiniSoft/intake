// Audio of a meeting is kept on this computer first, in IndexedDB, and uploaded from there. A chunk leaves the
// store only once the server has confirmed it, so a dropped connection, a closed tab or a slow line delays the
// upload instead of losing sound.

export type StoredChunk = { meetingId: string; sequence: number; blob: Blob; createdAt: number }
// One record per meeting this browser is still responsible for: recording, or stopped and not yet fully uploaded.
export type PendingRecording = { meetingId: string; projectCode: string; startedAt: number; elapsed: number; stopped: boolean; nextSequence: number }

const DB = 'intake-recording'
const VERSION = 1

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('chunks')) {
        const chunks = db.createObjectStore('chunks', { keyPath: ['meetingId', 'sequence'] })
        chunks.createIndex('byMeeting', 'meetingId')
      }
      if (!db.objectStoreNames.contains('meetings')) db.createObjectStore('meetings', { keyPath: 'meetingId' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
    request.onblocked = () => reject(new Error('IndexedDB blocked'))
  })
}

function done<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function run<T>(store: string, mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open()
  try {
    return await done(work(db.transaction(store, mode).objectStore(store)))
  } finally {
    db.close()
  }
}

export const recordingStore = {
  available: () => typeof indexedDB !== 'undefined',
  putChunk: (chunk: StoredChunk) => run('chunks', 'readwrite', (store) => store.put(chunk)),
  deleteChunk: (meetingId: string, sequence: number) => run('chunks', 'readwrite', (store) => store.delete([meetingId, sequence])),
  chunksOf: async (meetingId: string): Promise<StoredChunk[]> => {
    const rows = await run('chunks', 'readonly', (store) => store.index('byMeeting').getAll(meetingId) as IDBRequest<StoredChunk[]>)
    return rows.sort((a, b) => a.sequence - b.sequence)
  },
  putMeeting: (record: PendingRecording) => run('meetings', 'readwrite', (store) => store.put(record)),
  meeting: (meetingId: string) => run('meetings', 'readonly', (store) => store.get(meetingId) as IDBRequest<PendingRecording | undefined>),
  pending: () => run('meetings', 'readonly', (store) => store.getAll() as IDBRequest<PendingRecording[]>),
  // The meeting is on the server in full: nothing of it stays here.
  forget: async (meetingId: string) => {
    const db = await open()
    try {
      const transaction = db.transaction(['chunks', 'meetings'], 'readwrite')
      const chunks = transaction.objectStore('chunks')
      const keys = await done(chunks.index('byMeeting').getAllKeys(meetingId))
      keys.forEach((key) => chunks.delete(key))
      transaction.objectStore('meetings').delete(meetingId)
      await new Promise<void>((resolve, reject) => { transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error) })
    } finally {
      db.close()
    }
  },
}
